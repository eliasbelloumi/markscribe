"""PDF smart OCR: page analysis, triage UI, parallel Gemini OCR."""

import base64
import hashlib
import io
import json
import threading
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pdfplumber
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table

from ._ui import console, fmt_time

CACHE_DIR = Path.home() / ".cache" / "markscribe"
RATE_LIMIT_RPM = 12
MAX_WORKERS = 4


def _needs_ocr(page) -> tuple[bool, str]:
    """Heuristic: decide if a PDF page needs visual OCR."""
    text = page.extract_text() or ""
    stripped = text.strip()
    page_area = page.width * page.height

    big_imgs = small_imgs = 0
    if hasattr(page, "images") and page.images:
        for img in page.images:
            w = img.get("x1", 0) - img.get("x0", 0)
            h = img.get("bottom", 0) - img.get("top", 0)
            if w <= 20 or h <= 20:
                continue
            area_pct = (w * h) / page_area if page_area else 0
            if area_pct > 0.05:
                big_imgs += 1
            else:
                small_imgs += 1

    vec_count = 0
    if hasattr(page, "objects"):
        for t in ("line", "rect", "curve"):
            vec_count += len(page.objects.get(t, []))

    n_words = len(stripped.split()) if stripped else 0

    if len(stripped) < 20:
        return True, "nearly empty"

    lines = [ln for ln in stripped.split("\n") if ln.strip()]
    n_lines = max(len(lines), 1)
    avg_words_per_line = n_words / n_lines
    short_lines = sum(1 for ln in lines if len(ln.split()) <= 2)
    short_lines_ratio = short_lines / n_lines
    has_punctuation = any(c in text for c in ".,:;!?")

    if big_imgs > 0:
        return True, f"img={big_imgs} ({n_words}w text)"
    if small_imgs > 8:
        return True, f"icons={small_imgs} ({n_words}w text)"
    if vec_count > 50:
        return True, f"vec={vec_count} ({n_words}w text)"
    if vec_count > 15 and n_words < 80:
        return True, f"vec={vec_count} + sparse text ({n_words}w)"
    if avg_words_per_line < 3 and short_lines_ratio > 0.6:
        return True, f"sparse labels ({n_words}w/{n_lines}l)"
    if not has_punctuation and n_words < 30:
        return True, f"no structure ({n_words}w)"
    if short_lines_ratio > 0.7 and n_words < 50:
        return True, f"fragmented ({short_lines}/{n_lines} short)"

    return False, f"ok ({n_words}w)"


def _generate_triage_ui(
    filepath: Path,
    detected: list[int],
    page_info: list[dict],
    total: int,
) -> set[int]:
    """Serve a local web page for manual page triage. Returns selected 0-indexed page set."""
    with console.status("[dim]Rendering thumbnails...[/dim]"):
        thumbs = []
        with pdfplumber.open(str(filepath)) as pdf:
            for i in detected:
                page = pdf.pages[i]
                img = page.to_image(resolution=150)
                buf = io.BytesIO()
                img.original.save(buf, format="JPEG", quality=70)
                b64 = base64.b64encode(buf.getvalue()).decode()
                thumbs.append({"page": i + 1, "b64": b64, "reason": page_info[i]["reason"]})
                page.close()

    fname = filepath.name
    pages_data = json.dumps(thumbs)

    html = f'''<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>markscribe — {fname}</title>
<style>
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{font-family:system-ui;background:#111;color:#eee;display:flex;flex-direction:column;
    height:100vh;overflow:hidden;user-select:none}}
  .top{{padding:12px 20px;display:flex;justify-content:space-between;align-items:center;
    background:#1a1a2e;border-bottom:1px solid #333}}
  .top h1{{font-size:1em;font-weight:500}}
  .stats{{font-family:monospace;font-size:.82em;color:#888;display:flex;gap:16px}}
  .stats b{{color:#4ade80}} .stats .skip{{color:#ef4444}}
  .viewer{{flex:1;display:flex;align-items:center;justify-content:center;padding:16px;
    position:relative;overflow:hidden}}
  .viewer img{{max-height:100%;max-width:100%;object-fit:contain;border-radius:6px;
    box-shadow:0 4px 24px #0008;transition:opacity .15s}}
  .badge{{position:absolute;top:24px;right:24px;padding:4px 12px;border-radius:4px;
    font-size:.75em;background:#333;color:#aaa}}
  .page-num{{position:absolute;top:24px;left:24px;padding:4px 12px;border-radius:4px;
    font-size:.85em;font-weight:600;background:#1a1a2e;color:#eee;font-family:monospace}}
  .controls{{padding:16px 20px;background:#1a1a2e;border-top:1px solid #333;
    display:flex;justify-content:center;gap:16px;align-items:center}}
  .btn{{padding:10px 28px;border:none;border-radius:6px;font-size:1em;font-weight:600;
    cursor:pointer;transition:.12s}}
  .btn-no{{background:#ef4444;color:#fff}} .btn-no:hover{{background:#dc2626}}
  .btn-yes{{background:#4ade80;color:#000}} .btn-yes:hover{{background:#22c55e}}
  .btn-back{{background:#333;color:#eee;font-size:.85em;padding:8px 16px}}
  .btn-back:hover{{background:#444}}
  .btn-done{{background:#8b5cf6;color:#fff;padding:12px 36px;font-size:1.1em}}
  .btn-done:hover{{background:#7c3aed}}
  .shortcuts{{font-size:.7em;color:#555;margin-top:2px;text-align:center}}
  kbd{{background:#222;padding:1px 6px;border-radius:3px;font-family:monospace;color:#999;
    border:1px solid #333}}
  .bar-wrap{{padding:0 20px 4px;background:#111}}
  .bar-bg{{height:3px;background:#222;border-radius:2px;overflow:hidden}}
  .bar-fill{{height:100%;background:linear-gradient(90deg,#4ade80,#22d3ee);transition:width .2s}}
  .done-screen{{display:flex;flex-direction:column;align-items:center;justify-content:center;
    height:100vh;gap:16px}}
  .done-screen h2{{color:#4ade80;font-size:1.5em}}
  .done-stats{{display:flex;gap:24px;font-family:monospace;font-size:.9em;color:#888}}
  .done-stats span{{display:flex;flex-direction:column;align-items:center;gap:4px}}
  .done-stats b{{font-size:1.4em}}
  .done-stats .green{{color:#4ade80}} .done-stats .red{{color:#ef4444}}
  .done-stats .blue{{color:#22d3ee}}
</style></head>
<body>
<div class="top">
  <h1>markscribe — {fname}</h1>
  <div class="stats">
    <div><b id="kept">0</b> kept</div>
    <div><span class="skip" id="skipped">0</span> skipped</div>
    <div><span id="pos">1</span>/{len(thumbs)}</div>
  </div>
</div>
<div class="bar-wrap"><div class="bar-bg"><div class="bar-fill" id="bar" style="width:0%"></div></div></div>
<div class="viewer">
  <div class="page-num" id="pagenum"></div>
  <img id="img">
  <div class="badge" id="badge"></div>
</div>
<div class="controls" id="controls">
  <button class="btn btn-back" id="back-btn" onclick="back()">&#8592; Back</button>
  <button class="btn btn-no" onclick="decide(false)">&#10005; Skip <small>(N)</small></button>
  <button class="btn btn-yes" onclick="decide(true)">&#10003; Keep <small>(Y / &rarr;)</small></button>
</div>
<div class="shortcuts">
  <kbd>&larr;</kbd> back &nbsp;&nbsp;
  <kbd>&rarr;</kbd> <kbd>Y</kbd> keep &nbsp;&nbsp;
  <kbd>N</kbd> skip &nbsp;&nbsp;
  <kbd>Enter</kbd> confirm
</div>
<script>
const pages={pages_data};
const total={total};
const decisions=new Array(pages.length).fill(null);
let cur=0;
const t0=Date.now();

function render(){{
  if(cur>=pages.length){{showDone();return;}}
  const p=pages[cur];
  document.getElementById('img').src='data:image/jpeg;base64,'+p.b64;
  document.getElementById('badge').textContent=p.reason;
  document.getElementById('pagenum').textContent='Page '+p.page+' / '+total;
  document.getElementById('pos').textContent=(cur+1);
  document.getElementById('kept').textContent=decisions.filter(d=>d===true).length;
  document.getElementById('skipped').textContent=decisions.filter(d=>d===false).length;
  document.getElementById('back-btn').style.visibility=cur>0?'visible':'hidden';
  document.getElementById('bar').style.width=((cur/pages.length)*100)+'%';
}}

function decide(keep){{decisions[cur]=keep;cur++;render();}}
function back(){{if(cur>0){{cur--;decisions[cur]=null;render();}}}}

function showDone(){{
  const kept=decisions.filter(d=>d===true).length;
  const skipped=decisions.filter(d=>d===false).length;
  const elapsed=((Date.now()-t0)/1000).toFixed(0);
  const keptPages=decisions.map((d,i)=>d===true?pages[i].page:null).filter(Boolean);
  const estMin=Math.ceil(kept*4/60);
  document.body.innerHTML=`
    <div class="done-screen">
      <h2>Triage done</h2>
      <div class="done-stats">
        <span><b class="green">${{kept}}</b>kept</span>
        <span><b class="red">${{skipped}}</b>skipped</span>
        <span><b class="blue">${{elapsed}}s</b>triage</span>
        <span><b style="color:#a78bfa">~${{estMin}}m</b>est. OCR</span>
      </div>
      <p style="color:#555;font-size:.8em;max-width:500px;text-align:center">
        Pages: ${{keptPages.join(', ')||'none'}}
      </p>
      <button class="btn btn-done" onclick="submit(${{JSON.stringify(keptPages)}})">
        Run OCR (${{kept}} pages)
      </button>
      <p style="color:#444;font-size:.75em"><kbd>Enter</kbd> to confirm</p>
    </div>`;
  window._finalPages=keptPages;
}}

async function submit(sel){{
  document.querySelector('.btn-done').disabled=true;
  document.querySelector('.btn-done').textContent='Sent...';
  await fetch('/submit',{{method:'POST',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{pages:sel}})}});
  document.body.innerHTML='<div class="done-screen"><h2 style="color:#4ade80">Running — check your terminal</h2></div>';
}}

document.addEventListener('keydown',e=>{{
  if(document.querySelector('.done-screen')){{
    if(e.key==='Enter'&&window._finalPages)submit(window._finalPages);
    return;
  }}
  if(e.key==='ArrowRight'||e.key==='y'||e.key==='Y') decide(true);
  else if(e.key==='n'||e.key==='N') decide(false);
  else if(e.key==='ArrowLeft') back();
}});

render();
</script>
</body></html>'''

    result_pages: list = []

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode())

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            result_pages.extend(body.get("pages", []))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
            threading.Thread(target=self.server.shutdown).start()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    url = f"http://localhost:{port}"

    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    webbrowser.open(url)
    console.print(f"  [cyan]Triage →[/cyan] [dim]{url}[/dim]")

    thread.join()
    return {int(p) - 1 for p in result_pages}


def smart_ocr(filepath: Path, client, ocr_mode: str, model: str, prompt: str) -> str:
    """Full OCR pipeline: analyse → (triage) → render → parallel OCR → assemble."""
    fname = filepath.name
    t_start = time.time()

    file_hash = hashlib.md5(str(filepath).encode()).hexdigest()[:10]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"pick_{file_hash}.json"

    if ocr_mode == "retry" and cache_path.exists():
        with open(cache_path) as f:
            cached = json.load(f)
        ocr_pages = set(cached["pages"])
        total = cached["total"]
        console.print(f"  [cyan]↻[/cyan] Resuming: [green]{len(ocr_pages)}[/green] pages from cache")
    else:
        # Phase 1: analyse pages
        page_info: list[dict] = []
        with pdfplumber.open(str(filepath)) as pdf:
            total = len(pdf.pages)
            with Progress(
                SpinnerColumn(),
                TextColumn("[cyan]Analysing[/cyan] {task.description}"),
                console=console,
                transient=True,
            ) as progress:
                task_id = progress.add_task(f"0/{total}", total=total)
                for i, page in enumerate(pdf.pages):
                    needs, reason = _needs_ocr(page)
                    page_info.append({"needs_ocr": needs, "reason": reason})
                    page.close()
                    progress.update(task_id, advance=1, description=f"{i + 1}/{total}")

        detected = [i for i, p in enumerate(page_info) if p["needs_ocr"]]
        n_text = total - len(detected)
        console.print(f"  [green]{n_text}[/green] text  [yellow]{len(detected)}[/yellow] visual")

        # auto-pick when >= 10 visual pages; always pick in pick mode
        use_pick = ocr_mode == "pick" or (ocr_mode == "auto" and len(detected) >= 10)

        if use_pick:
            if not detected:
                console.print("  [dim]No visual pages — skipping triage[/dim]")
                ocr_pages = set()
            else:
                ocr_pages = _generate_triage_ui(filepath, detected, page_info, total)
            n_skip = len(detected) - len(ocr_pages)
            console.print(
                f"  [cyan]Triage[/cyan] [green]{len(ocr_pages)}[/green] kept  "
                f"[dim]{n_skip} skipped[/dim]"
            )
        else:
            ocr_pages = set(detected)
            if ocr_pages:
                console.print(f"  [cyan]▸[/cyan] {len(ocr_pages)} pages → auto OCR")

        if ocr_pages:
            with open(cache_path, "w") as f:
                json.dump({"pages": sorted(ocr_pages), "total": total}, f)

    if not ocr_pages:
        parts = []
        with pdfplumber.open(str(filepath)) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                if text.strip():
                    parts.append(f"## Page {i + 1}\n\n{text.strip()}")
                page.close()
        return "\n\n".join(parts)

    # Phase 2: render pages to images
    ocr_images: dict[int, str] = {}
    text_parts: dict[int, str] = {}
    with pdfplumber.open(str(filepath)) as pdf:
        with Progress(
            SpinnerColumn(),
            TextColumn("[cyan]Rendering[/cyan]"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
            transient=True,
        ) as progress:
            task_id = progress.add_task("", total=len(ocr_pages))
            for i in sorted(ocr_pages):
                page = pdf.pages[i]
                img = page.to_image(resolution=300)
                buf = io.BytesIO()
                img.original.save(buf, format="PNG")
                ocr_images[i] = base64.b64encode(buf.getvalue()).decode()
                page.close()
                progress.advance(task_id)
        for i, page in enumerate(pdf.pages):
            if i not in ocr_pages:
                text = page.extract_text() or ""
                if text.strip():
                    text_parts[i] = text.strip()
            page.close()

    # Phase 3: parallel OCR
    n_ocr = len(ocr_images)
    console.print(f"  [cyan]OCR[/cyan] {n_ocr} pages → Gemini [dim]({model})[/dim]")

    rate_lock = threading.Lock()
    rate_times: list[float] = []
    stats = {"done": 0, "retries": 0, "tokens_in": 0, "tokens_out": 0}
    t_ocr = time.time()

    def _throttled_ocr(page_idx: int, b64: str) -> tuple[int, str, dict]:
        from openai import RateLimitError

        for attempt in range(5):
            with rate_lock:
                now = time.monotonic()
                rate_times[:] = [t for t in rate_times if now - t < 60]
                if len(rate_times) >= RATE_LIMIT_RPM:
                    wait = 60 - (now - rate_times[0]) + 0.5
                    rate_lock.release()
                    time.sleep(wait)
                    rate_lock.acquire()
                    rate_times[:] = [t for t in rate_times if time.monotonic() - t < 60]
                rate_times.append(time.monotonic())
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {
                                "url": f"data:image/png;base64,{b64}"
                            }},
                        ],
                    }],
                )
                usage: dict = {}
                if hasattr(response, "usage") and response.usage:
                    usage = {
                        "in": getattr(response.usage, "prompt_tokens", 0) or 0,
                        "out": getattr(response.usage, "completion_tokens", 0) or 0,
                    }
                return page_idx, response.choices[0].message.content, usage
            except RateLimitError:
                stats["retries"] += 1
                time.sleep(min(15 * (attempt + 1), 60))

        raise RuntimeError(f"p.{page_idx + 1}: failed after 5 attempts (rate limit)")

    ocr_results: dict[int, str] = {}

    with Progress(
        TextColumn("[cyan]OCR[/cyan]"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task("", total=n_ocr)
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {
                pool.submit(_throttled_ocr, i, b64): i
                for i, b64 in ocr_images.items()
            }
            for future in as_completed(futures):
                page_idx, text, usage = future.result()
                ocr_results[page_idx] = text
                stats["done"] += 1
                stats["tokens_in"] += usage.get("in", 0)
                stats["tokens_out"] += usage.get("out", 0)
                progress.advance(task_id)

    elapsed_total = time.time() - t_start

    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_row("[dim]pages text[/dim]", f"[green]{total - n_ocr}[/green]")
    table.add_row("[dim]pages OCR[/dim]", f"[cyan]{n_ocr}[/cyan]")
    if stats["tokens_in"] or stats["tokens_out"]:
        table.add_row(
            "[dim]tokens[/dim]",
            f"[dim]{stats['tokens_in']:,} in · {stats['tokens_out']:,} out[/dim]",
        )
    if stats["retries"]:
        table.add_row("[dim]retries[/dim]", f"[yellow]{stats['retries']}[/yellow]")
    table.add_row("[dim]duration[/dim]", f"[dim]{fmt_time(elapsed_total)}[/dim]")
    console.print(Panel(table, title="[green]✓ Done[/green]", border_style="dim green", padding=(0, 1)))

    # Assemble pages in order
    parts = []
    last_page = max(max(ocr_results, default=-1), max(text_parts, default=-1))
    for i in range(last_page + 1):
        if i in ocr_results:
            parts.append(f"## Page {i + 1}\n\n{ocr_results[i]}")
        elif i in text_parts:
            parts.append(f"## Page {i + 1}\n\n{text_parts[i]}")
    return "\n\n".join(parts)
