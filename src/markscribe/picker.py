"""Native file/folder pickers. macOS only via osascript; fallback: require CLI arg."""

import platform
import subprocess
from pathlib import Path


def _run_osascript(script: str) -> str | None:
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def pick_input() -> Path | None:
    """Open a native file-or-folder picker. Returns None if cancelled or not on macOS."""
    if platform.system() != "Darwin":
        return None

    choice = _run_osascript(
        'tell application "System Events" to button returned of '
        '(display dialog "What do you want to convert?" '
        'buttons {"Cancel", "Folder", "File"} default button "File" '
        'with title "markscribe")'
    )
    if not choice or choice == "Cancel":
        return None

    if choice == "File":
        path_str = _run_osascript(
            'tell app "System Events" to POSIX path of '
            '(choose file with prompt "Choose a file to convert")'
        )
    else:
        path_str = _run_osascript(
            'tell app "System Events" to POSIX path of '
            '(choose folder with prompt "Choose a folder to convert")'
        )

    if not path_str:
        return None
    return Path(path_str.rstrip("/"))


def pick_output_dir() -> Path | None:
    """Open a native folder picker for the output directory. macOS only."""
    if platform.system() != "Darwin":
        return None

    path_str = _run_osascript(
        'tell app "System Events" to POSIX path of '
        '(choose folder with prompt "Choose output folder")'
    )
    if not path_str:
        return None
    return Path(path_str.rstrip("/"))


def open_path(path: Path) -> None:
    """Open a file or folder with the system default app."""
    if platform.system() == "Darwin":
        subprocess.run(["open", str(path)], check=False)
    elif platform.system() == "Linux":
        subprocess.run(["xdg-open", str(path)], check=False)
