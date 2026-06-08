import os
import stat
import tomllib
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "markscribe"
CONFIG_FILE = CONFIG_DIR / "config.toml"


def get_api_key() -> str | None:
    """Return API key: env var takes priority over config file."""
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "rb") as f:
            data = tomllib.load(f)
        return data.get("gemini_api_key") or None
    return None


def set_api_key(key: str) -> None:
    """Write key to config file with mode 600."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    existing: dict = {}
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE, "rb") as f:
            existing = tomllib.load(f)
    existing["gemini_api_key"] = key
    with open(CONFIG_FILE, "w") as f:
        for k, v in existing.items():
            f.write(f'{k} = "{v}"\n')
    CONFIG_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)


def clear_api_key() -> bool:
    """Remove stored key. Returns True if a key was present."""
    if not CONFIG_FILE.exists():
        return False
    with open(CONFIG_FILE, "rb") as f:
        data = tomllib.load(f)
    if "gemini_api_key" not in data:
        return False
    del data["gemini_api_key"]
    if data:
        with open(CONFIG_FILE, "w") as f:
            for k, v in data.items():
                f.write(f'{k} = "{v}"\n')
        CONFIG_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)
    else:
        CONFIG_FILE.unlink()
    return True


def mask_key(key: str) -> str:
    if len(key) <= 8:
        return "***"
    return key[:4] + "..." + key[-4:]
