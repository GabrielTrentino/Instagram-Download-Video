"""Preferências do usuário, salvas fora do repositório (em %APPDATA% no Windows)."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

APP_NAME = "InstagramVideoDownloader"

def _app_root() -> Path:
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parent.parent
    # Executável (PyInstaller): o código roda de uma pasta temporária, então a raiz é o
    # repositório onde o .exe está (ex.: <repo>/dist/app.exe) ou, fora dele, a pasta do .exe.
    exe_dir = Path(sys.executable).resolve().parent
    return next((p for p in (exe_dir, *exe_dir.parents) if (p / ".git").exists()), exe_dir)


# Raiz do repositório/aplicativo. Downloads e histórico nunca devem ficar aqui dentro.
APP_ROOT = _app_root()


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or Path.home() / ".config"
    return Path(base) / APP_NAME


def default_download_dir() -> Path:
    videos = Path.home() / "Videos"
    return (videos if videos.is_dir() else Path.home()) / "Instagram Downloads"


def is_inside(path: Path, parent: Path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(parent).resolve())
    except ValueError:
        return False
    return True


@dataclass
class Settings:
    download_dir: str = field(default_factory=lambda: str(default_download_dir()))
    max_workers: int = 2
    cookies_browser: str = ""  # "", "firefox", "chrome", "edge", ...
    cookies_file: str = ""  # caminho para um cookies.txt (formato Netscape)
    skip_existing: bool = True

    @staticmethod
    def exists(path: Path | None = None) -> bool:
        return Path(path or config_dir() / "config.json").is_file()

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        path = path or config_dir() / "config.json"
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        if not isinstance(data, dict):
            return cls()
        settings = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        if not settings.download_dir or is_inside(Path(settings.download_dir), APP_ROOT):
            settings.download_dir = str(default_download_dir())
        return settings

    def save(self, path: Path | None = None) -> None:
        path = Path(path or config_dir() / "config.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
