"""CLI entry point.

Two separate typer apps routed in app_entry():
  main_app  — conversion:  markscribe [PATH] [OPTIONS]
  config_app — key mgmt:   markscribe config COMMAND
"""

import os
import platform
import sys
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.panel import Panel
from rich.table import Table

from . import __version__
from ._ui import console
from .config import clear_api_key, get_api_key, mask_key, set_api_key
from .converter import SUPPORTED_EXTENSIONS, get_md


def _will_use_ocr(path: Path, ocr_mode: str) -> bool:
    return (
        path.suffix.lower().lstrip(".") == "pdf"
        and get_api_key() is not None
        and ocr_mode != "off"
    )
from .picker import open_path, pick_input, pick_output_dir

DEFAULT_OUT = Path.home() / ".cache" / "markscribe" / "out"

# ── main conversion app ──────────────────────────────────────────────────────

main_app = typer.Typer(no_args_is_help=False, rich_markup_mode="rich")


@main_app.command(no_args_is_help=False)
def convert(
    path: Annotated[Optional[Path], typer.Argument(help="File or folder to convert")] = None,
    ocr: Annotated[str, typer.Option("--ocr", help="OCR mode: auto · off · pick · retry")] = "auto",
    out: Annotated[Optional[Path], typer.Option("--out", help="Output directory")] = None,
    clean: Annotated[bool, typer.Option("--clean", help="Clear OCR cache and exit")] = False,
    version: Annotated[bool, typer.Option("--version", "-v", help="Show version")] = False,
) -> None:
    """Convert files or folders to Markdown."""
    if version:
        console.print(f"markscribe {__version__}")
        raise typer.Exit()

    if clean:
        _do_clean()
        raise typer.Exit()

    out_dir = out

    if path is None:
        picked = pick_input()
        if picked is None:
            if platform.system() != "Darwin":
                console.print("[red]Error:[/red] provide a path as argument (GUI picker is macOS only)")
            raise typer.Abort()
        path = picked
        if out_dir is None:
            picked_out = pick_output_dir()
            if picked_out is not None:
                out_dir = picked_out

    if not path.exists():
        console.print(f"[red]Not found:[/red] {path}")
        raise typer.Exit(1)

    out_dir = out_dir or DEFAULT_OUT

    if path.is_file():
        _convert_file(path, ocr, out_dir)
    elif path.is_dir():
        _convert_folder(path, ocr, out_dir)
    else:
        console.print(f"[red]Error:[/red] {path} is neither a file nor a directory")
        raise typer.Exit(1)


# ── config app ───────────────────────────────────────────────────────────────

config_app = typer.Typer(no_args_is_help=True, rich_markup_mode="rich")


@config_app.command("set-key")
def config_set_key(
    key: Annotated[str, typer.Argument(help="Gemini API key")],
) -> None:
    """Store Gemini API key in [dim]~/.config/markscribe/config.toml[/dim] (mode 600)."""
    set_api_key(key)
    console.print(f"[green]Key saved[/green] — [dim]{mask_key(key)}[/dim]")


@config_app.command("show")
def config_show() -> None:
    """Show current configuration."""
    key = get_api_key()
    table = Table(show_header=False, box=None, padding=(0, 2))
    if key:
        source = "env GEMINI_API_KEY" if os.environ.get("GEMINI_API_KEY") else "~/.config/markscribe/config.toml"
        table.add_row("[dim]key[/dim]", f"[green]{mask_key(key)}[/green]  [dim]({source})[/dim]")
    else:
        table.add_row("[dim]key[/dim]", "[yellow]not set[/yellow]  [dim]OCR disabled[/dim]")
    table.add_row("[dim]version[/dim]", f"[dim]{__version__}[/dim]")
    console.print(Panel(table, title="markscribe config", border_style="dim"))


@config_app.command("clear")
def config_clear() -> None:
    """Remove stored API key."""
    if clear_api_key():
        console.print("[green]Key removed[/green]")
    else:
        console.print("[dim]No stored key[/dim]")


# ── entry point ──────────────────────────────────────────────────────────────

def app_entry() -> None:
    """Route 'markscribe config ...' to config_app, everything else to main_app."""
    if len(sys.argv) > 1 and sys.argv[1] == "config":
        sys.argv.pop(1)
        config_app()
    else:
        main_app()


# ── helpers ──────────────────────────────────────────────────────────────────

def _convert_file(path: Path, ocr: str, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{path.stem}.md"
    console.print(f"\n  [dim]{path.name}[/dim]")
    if _will_use_ocr(path, ocr):
        result = get_md(path, ocr)
    else:
        with console.status("[dim]Converting...[/dim]"):
            result = get_md(path, ocr)
    dest.write_text(result, encoding="utf-8")
    console.print(f"  [green]→[/green] {dest}")
    open_path(dest)


def _convert_folder(folder: Path, ocr: str, out_dir: Path) -> None:
    files = [
        f for f in folder.iterdir()
        if f.is_file() and f.suffix.lower().lstrip(".") in SUPPORTED_EXTENSIONS
    ]
    skipped = [
        f for f in folder.iterdir()
        if f.is_file() and f.suffix.lower().lstrip(".") not in SUPPORTED_EXTENSIONS
    ]

    if not files:
        console.print("[yellow]No supported files found.[/yellow]")
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    ok = errors = 0
    n = len(files)

    for idx, f in enumerate(files, 1):
        console.print(f"\n  [{idx}/{n}] [dim]{f.name}[/dim]")
        try:
            if _will_use_ocr(f, ocr):
                result = get_md(f, ocr)
            else:
                with console.status("[dim]Converting...[/dim]"):
                    result = get_md(f, ocr)
            dest = out_dir / f"{f.stem}.md"
            dest.write_text(result, encoding="utf-8")
            console.print(f"  [green]✓[/green] {f.name}")
            ok += 1
        except Exception as e:
            console.print(f"  [red]✗[/red] {f.name}: {e}")
            errors += 1

    for f in skipped:
        console.print(f"  [dim]skip  {f.name}[/dim]")

    console.print(
        f"\n[green]{ok}[/green] converted"
        + (f", [red]{errors}[/red] errors" if errors else "")
        + f" → {out_dir}"
    )
    open_path(out_dir)


def _do_clean() -> None:
    from shutil import rmtree
    from .ocr import CACHE_DIR

    if CACHE_DIR.exists():
        rmtree(CACHE_DIR)
        console.print(f"[green]Cleared[/green] {CACHE_DIR}")
    else:
        console.print("[dim]Nothing to clear[/dim]")
