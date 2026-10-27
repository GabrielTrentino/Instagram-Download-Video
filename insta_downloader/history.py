"""Histórico de downloads, salvo como JSON dentro da pasta escolhida pelo usuário."""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

HISTORY_FILENAME = "historico_downloads.json"


def format_size(num_bytes: float) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


@dataclass
class HistoryEntry:
    url: str
    ok: bool
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    title: str = ""
    uploader: str = ""
    files: list[str] = field(default_factory=list)
    size_bytes: int = 0
    error: str = ""

    @property
    def date(self) -> datetime:
        return datetime.fromisoformat(self.timestamp)


@dataclass
class HistoryStats:
    successes: int = 0
    failures: int = 0
    files: int = 0
    total_bytes: int = 0
    last_success: HistoryEntry | None = None

    @property
    def success_rate(self) -> float | None:
        total = self.successes + self.failures
        return self.successes / total if total else None


class History:
    """Lista de downloads persistida em disco. Segura para uso entre threads."""

    def __init__(self, folder: Path | str):
        self.path = Path(folder) / HISTORY_FILENAME
        self._lock = threading.Lock()
        self._entries = self._load()

    def _load(self) -> list[HistoryEntry]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, ValueError):
            # Preserva o arquivo ilegível em vez de sobrescrevê-lo no próximo salvamento.
            try:
                self.path.replace(self.path.with_suffix(".corrompido.json"))
            except OSError:
                pass
            return []
        known = HistoryEntry.__dataclass_fields__
        return [
            HistoryEntry(**{k: v for k, v in item.items() if k in known})
            for item in raw.get("entries", [])
            if isinstance(item, dict) and "url" in item and "ok" in item
        ]

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"version": 1, "entries": [asdict(e) for e in self._entries]}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def add(self, entry: HistoryEntry) -> None:
        with self._lock:
            self._entries.append(entry)
            self._save()

    def clear(self) -> None:
        with self._lock:
            self._entries = []
            self._save()

    def recent(self, limit: int = 200) -> list[HistoryEntry]:
        """Entradas mais recentes primeiro."""
        with self._lock:
            return list(reversed(self._entries[-limit:]))

    def stats(self) -> HistoryStats:
        stats = HistoryStats()
        with self._lock:
            for entry in self._entries:
                if entry.ok:
                    stats.successes += 1
                    stats.files += len(entry.files)
                    stats.total_bytes += entry.size_bytes
                    stats.last_success = entry
                else:
                    stats.failures += 1
        return stats
