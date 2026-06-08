# markscribe

Convert any document to clean Markdown — with smart OCR for visual PDFs.

Built on [MarkItDown](https://github.com/microsoft/markitdown) (Microsoft), markscribe adds a page-level OCR pipeline that handles the cases where MarkItDown produces empty or garbled output: scanned PDFs, diagram-heavy slides, and pages where the text layer is sparse or absent.

Shield: [![CC BY-NC-SA 4.0][cc-by-nc-sa-shield]][cc-by-nc-sa]

  This work is licensed under a
  [Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International
  License][cc-by-nc-sa].

  [![CC BY-NC-SA 4.0][cc-by-nc-sa-image]][cc-by-nc-sa]

  [cc-by-nc-sa]: http://creativecommons.org/licenses/by-nc-sa/4.0/
  [cc-by-nc-sa-image]: https://licensebuttons.net/l/by-nc-sa/4.0/88x31.png
  [cc-by-nc-sa-shield]:
  https://img.shields.io/badge/License-CC%20BY--NC--SA%204.0-lightgrey.svg

---

## Why markscribe instead of MarkItDown directly

MarkItDown reliably converts structured documents: Word files, spreadsheets, HTML, audio transcriptions. PDFs with a proper text layer work fine too.

It struggles with:

- Scanned pages (no text layer at all)
- Pages with complex diagrams, flowcharts, or infographics
- Slides where the content is mostly vector graphics and short labels
- Any page where `pdfplumber` extracts fewer than 30 words or finds no punctuation

markscribe analyses each PDF page before deciding whether to call the API. For pages that pass the text quality check, it extracts text locally with `pdfplumber`. Only pages that fail the check are sent to Gemini as images.

**Result:** a mixed document with 40 text pages and 8 diagram pages costs 8 API calls, not 48.

### How the heuristic works

For each page, markscribe checks:

- **Image coverage:** large images occupying more than 5% of the page area
- **Vector object count:** more than 50 lines, rects, or curves (typical of diagrams)
- **Text density:** average words per line below 3 (typical of label-heavy slides)
- **Punctuation absence:** fewer than 30 words with no sentence-ending punctuation
- **Fragmented lines:** more than 70% of lines contain 2 words or fewer

A page that triggers any of these rules is flagged as visual. All other pages are extracted locally.

### Triage mode

When 10 or more pages are flagged in a single PDF, markscribe opens a browser-based triage UI instead of sending them all automatically. You see a thumbnail of each flagged page, its detection reason, and keyboard shortcuts to keep or skip it:

- `→` or `Y` — keep (send to OCR)
- `N` — skip
- `←` — go back

After triage, the selection is cached. Use `--ocr retry` to re-run OCR with the same selection without going through triage again.

---

## Requirements

- Python >= 3.11
- [uv](https://docs.astral.sh/uv/) >= 0.4
- A Gemini API key — only required for OCR. Text-only conversions work without one.

---

## Installation

```bash
uv tool install path/to/markscribe
```

Verify:

```bash
markscribe --version
```

---

## Quick start

```bash
# Store your API key once
markscribe config set-key YOUR_GEMINI_API_KEY

# Convert a single file
markscribe report.pdf

# Convert a folder
markscribe ~/Downloads/slides/

# Launch a file/folder picker (macOS)
markscribe
```

Output files are written to `~/.cache/markscribe/out/` by default and opened automatically on macOS.

---

## Usage

```
markscribe [PATH] [OPTIONS]
markscribe config COMMAND
```

### Convert

| Argument / option | Description |
|---|---|
| `PATH` | File or folder to convert. Omit on macOS to open a native picker. |
| `--ocr auto` | Default. Detect visual pages, auto-triage when >= 10 found. |
| `--ocr off` | Disable OCR entirely. No API calls, text extraction only. |
| `--ocr pick` | Always open the triage UI for any detected visual page. |
| `--ocr retry` | Resume from the cached page selection without re-triaging. |
| `--out PATH` | Output directory. Default: `~/.cache/markscribe/out/`. |
| `--clean` | Delete `~/.cache/markscribe/` and exit. |

### Config

```bash
markscribe config set-key <API_KEY>   # store key in ~/.config/markscribe/config.toml
markscribe config show                # show active config (key is masked)
markscribe config clear               # remove stored key
```

The environment variable `GEMINI_API_KEY` takes priority over the stored key.

---

## Supported formats

| Category | Extensions |
|---|---|
| Documents | `pdf` `docx` `pptx` `xlsx` `xls` `epub` |
| Data | `csv` `json` `xml` `html` |
| Archives | `zip` |
| Media | `mp3` `wav` `jpg` `jpeg` `png` `gif` `webp` |

---

## Privacy

All processing is local except for one case: when OCR is active and a PDF page is classified as visual, that page is rendered to a PNG image and sent to the Gemini API.

Specifically:

- Text extraction via `pdfplumber` runs entirely on your machine.
- The heuristic analysis runs locally — no data leaves before the classification step.
- Only the image data of flagged PDF pages is transmitted, never the text content or metadata.
- Non-PDF formats are never sent to any external API.
- The API key is stored in `~/.config/markscribe/config.toml` with permissions `600` (readable only by your user). It is never written to any project file.
- markscribe has no telemetry and makes no network requests other than Gemini API calls when OCR is active.

To convert a PDF without any external calls, use `--ocr off`.

---

## OCR cache

When triage completes, the selected page indices are written to `~/.cache/markscribe/pick_<hash>.json`. This lets you re-run OCR on the same file (`--ocr retry`) without repeating the triage step.

Clear the cache at any time:

```bash
markscribe --clean
```
