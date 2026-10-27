"""Fila de downloads do Instagram via yt-dlp, com downloads simultâneos e progresso."""

from __future__ import annotations

import os
import re
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urlsplit, urlunsplit

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadCancelled

from .config import Settings
from .history import History, HistoryEntry, format_size

# Arquivo do yt-dlp que registra IDs já baixados (fica na pasta de destino).
ARCHIVE_FILENAME = ".download_archive.txt"
# Todos os vídeos ficam direto na pasta escolhida; o perfil vai no nome do arquivo.
OUTPUT_TEMPLATE = "%(uploader_id,uploader|perfil_desconhecido)s_%(upload_date>%Y-%m-%d|sem_data)s_%(id)s.%(ext)s"

_INSTAGRAM_HOSTS = {"instagram.com", "www.instagram.com", "m.instagram.com", "instagr.am", "www.instagr.am"}
_SEPARATORS = re.compile(r"[\s,;]+")
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def normalize_url(raw: str) -> str | None:
    """URL canônica do Instagram (sem parâmetros de rastreio), ou None se não for do Instagram."""
    candidate = raw.strip().strip("<>\"'()[]")
    if not candidate:
        return None
    if not re.match(r"^https?://", candidate, re.IGNORECASE):
        candidate = "https://" + candidate
    parts = urlsplit(candidate)
    host = (parts.hostname or "").lower()
    if host not in _INSTAGRAM_HOSTS or parts.path in ("", "/"):
        return None
    if host.endswith("instagram.com"):
        host = "www.instagram.com"
    path = parts.path if parts.path.endswith("/") else parts.path + "/"
    return urlunsplit(("https", host, path, "", ""))


def parse_sources(text: str) -> tuple[list[str], list[str]]:
    """Separa o texto em links válidos (sem duplicatas, na ordem) e trechos ignorados."""
    valid: list[str] = []
    invalid: list[str] = []
    for token in _SEPARATORS.split(text):
        if not token:
            continue
        url = normalize_url(token)
        if url is None:
            invalid.append(token)
        elif url not in valid:
            valid.append(url)
    return valid, invalid


class JobStatus(str, Enum):
    QUEUED = "Na fila"
    DOWNLOADING = "Baixando"
    PROCESSING = "Processando"
    DONE = "Concluído"
    SKIPPED = "Já baixado"
    FAILED = "Erro"
    CANCELLED = "Cancelado"

    @property
    def finished(self) -> bool:
        return self in _FINISHED


_FINISHED = {JobStatus.DONE, JobStatus.SKIPPED, JobStatus.FAILED, JobStatus.CANCELLED}


@dataclass
class Job:
    id: int
    url: str
    status: JobStatus = JobStatus.QUEUED
    progress: float = 0.0  # 0..1
    title: str = ""
    speed: str = ""
    error: str = ""
    files: list[str] = field(default_factory=list)


class _QuietLogger:
    """Silencia o yt-dlp e detecta quando um item é pulado por já estar no arquivo de registro."""

    def __init__(self) -> None:
        self.skipped_archive = False

    def debug(self, msg: str) -> None:
        if "already been recorded in the archive" in msg:
            self.skipped_archive = True

    info = debug

    def warning(self, msg: str) -> None:
        pass

    def error(self, msg: str) -> None:
        pass


def _display_title(info: dict) -> str:
    caption = (info.get("description") or "").strip().splitlines()
    text = caption[0] if caption else info.get("title") or ""
    return text[:100]


def _uploader(info: dict) -> str:
    entries = info.get("entries") or [{}]
    for source in (info, entries[0] or {}):
        for key in ("uploader_id", "uploader", "channel"):
            if source.get(key):
                return str(source[key])
    return ""


def _clean_error(exc: Exception) -> str:
    message = _ANSI.sub("", str(exc)).strip()
    message = re.sub(r"^ERROR:\s*", "", message)
    lowered = message.lower()
    if any(word in lowered for word in ("login", "cookies", "rate-limit", "not available")):
        message += " — dica: selecione os cookies de um navegador logado no Instagram."
    return message


class DownloadManager:
    """Executa uma lista de Jobs em paralelo. Os callbacks são chamados a partir de threads de trabalho."""

    def __init__(
        self,
        settings: Settings,
        history: History,
        on_job_update: Callable[[Job], None],
        on_finished: Callable[[], None],
    ):
        self.settings = settings
        self.history = history
        self._on_job_update = on_job_update
        self._on_finished = on_finished
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, jobs: Iterable[Job]) -> None:
        if self.running:
            raise RuntimeError("Já existe um lote de downloads em andamento.")
        self._cancel.clear()
        self._thread = threading.Thread(target=self._run_all, args=(list(jobs),), daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self._cancel.set()

    def _run_all(self, jobs: list[Job]) -> None:
        try:
            workers = max(1, int(self.settings.max_workers))
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="download") as pool:
                list(pool.map(self._run_job, jobs))
        finally:
            self._on_finished()

    def _update(self, job: Job, **changes) -> None:
        for key, value in changes.items():
            setattr(job, key, value)
        self._on_job_update(job)

    def _run_job(self, job: Job) -> None:
        if self._cancel.is_set():
            self._update(job, status=JobStatus.CANCELLED)
            return
        self._update(job, status=JobStatus.DOWNLOADING, progress=0.0)
        files: list[str] = []
        logger = _QuietLogger()
        try:
            with YoutubeDL(self._ydl_options(job, files, logger)) as ydl:
                info = ydl.extract_info(job.url, download=True)
        except DownloadCancelled:
            self._update(job, status=JobStatus.CANCELLED, speed="")
            return
        except Exception as exc:  # yt-dlp levanta vários tipos; todos viram "Erro" na fila
            message = _clean_error(exc)
            self._update(job, status=JobStatus.FAILED, error=message, speed="")
            self.history.add(HistoryEntry(url=job.url, ok=False, title=job.title, error=message))
            return

        if not files:
            note = "Já consta no registro de downloads." if logger.skipped_archive or info is None else ""
            self._update(job, status=JobStatus.SKIPPED, progress=1.0, speed="", error=note)
            return

        info = info or {}
        title = job.title or _display_title(info)
        size = sum(os.path.getsize(f) for f in files if os.path.exists(f))
        self._update(job, status=JobStatus.DONE, progress=1.0, speed="", files=files, title=title)
        self.history.add(
            HistoryEntry(
                url=job.url, ok=True, title=title, uploader=_uploader(info), files=files, size_bytes=size
            )
        )

    def _ydl_options(self, job: Job, files: list[str], logger: _QuietLogger) -> dict:
        settings = self.settings
        options = {
            "paths": {"home": settings.download_dir},
            "outtmpl": OUTPUT_TEMPLATE,
            # Com ffmpeg junta a melhor trilha de vídeo e áudio; sem ele usa o melhor arquivo único.
            "format": "bv*+ba/b" if ffmpeg_available() else "b/bv*",
            "merge_output_format": "mp4",
            "progress_hooks": [self._progress_hook(job)],
            "post_hooks": [files.append],
            "logger": logger,
            "noprogress": True,
            "socket_timeout": 30,
            "retries": 3,
            "windowsfilenames": True,
        }
        if settings.skip_existing:
            options["download_archive"] = str(Path(settings.download_dir) / ARCHIVE_FILENAME)
        if settings.cookies_file:
            options["cookiefile"] = settings.cookies_file
        elif settings.cookies_browser:
            options["cookiesfrombrowser"] = (settings.cookies_browser,)
        return options

    def _progress_hook(self, job: Job) -> Callable[[dict], None]:
        last_percent = -1

        def hook(d: dict) -> None:
            nonlocal last_percent
            if self._cancel.is_set():
                raise DownloadCancelled()
            info = d.get("info_dict") or {}
            changes: dict = {}
            if not job.title and _display_title(info):
                changes["title"] = _display_title(info)

            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                fraction = min(d.get("downloaded_bytes", 0) / total, 1.0) if total else 0.0
                # Vídeo + áudio separados contam como partes do mesmo item.
                part_ids = [f.get("format_id") for f in info.get("requested_formats") or []]
                part = part_ids.index(info.get("format_id")) if info.get("format_id") in part_ids else 0
                fraction = (part + fraction) / max(len(part_ids), 1)
                # Carrosséis (vários vídeos num post) contam como uma playlist.
                count = info.get("n_entries") or 1
                index = info.get("playlist_index") or 1
                progress = (index - 1 + fraction) / count
                percent = int(progress * 100)
                if percent == last_percent and not changes:
                    return
                last_percent = percent
                speed = d.get("speed")
                changes.update(
                    status=JobStatus.DOWNLOADING,
                    progress=progress,
                    speed=f"{format_size(speed)}/s" if speed else "",
                )
            elif d["status"] == "finished":
                changes.update(status=JobStatus.PROCESSING, speed="")

            if changes:
                self._update(job, **changes)

        return hook
