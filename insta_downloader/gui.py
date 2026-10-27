"""Interface gráfica (Tkinter) do Instagram Video Downloader."""

from __future__ import annotations

import dataclasses
import os
import queue
import subprocess
import sys
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk

from .config import APP_ROOT, Settings, is_inside
from .downloader import DownloadManager, Job, JobStatus, ffmpeg_available, parse_sources
from .history import History, HistoryEntry, format_size

COOKIE_FILE_LABEL = "Arquivo cookies.txt…"
COOKIE_BROWSERS = {
    "Nenhum": "",
    "Firefox": "firefox",
    "Chrome": "chrome",
    "Edge": "edge",
    "Brave": "brave",
    "Opera": "opera",
}
MAX_WORKERS = 5

STATUS_TAGS = {
    JobStatus.DONE: "ok",
    JobStatus.SKIPPED: "muted",
    JobStatus.CANCELLED: "muted",
    JobStatus.FAILED: "error",
}


def open_path(path: str | Path) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def reveal_in_folder(path: str | Path) -> None:
    if sys.platform == "win32":
        # O Explorer exige "/select," e o caminho entre aspas no mesmo argumento; uma lista
        # passada ao subprocess quotaria os dois separadamente e o Explorer abriria outra pasta.
        subprocess.Popen(f'explorer /select,"{os.path.normpath(path)}"')
    else:
        open_path(Path(path).parent)


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Instagram Video Downloader")
        self.geometry("1120x780")
        self.minsize(920, 640)

        first_run = not Settings.exists()
        self.settings = Settings.load()
        self.history = History(self.settings.download_dir)
        self.manager: DownloadManager | None = None
        self.jobs: dict[int, Job] = {}
        self._events: queue.Queue = queue.Queue()
        self._history_rows: list[HistoryEntry] = []

        self._build_styles()
        self._build_ui()
        self.refresh_history()
        self.after(150, self._poll_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        if first_run:
            self.after(300, self._ask_folder_first_run)

    def _ask_folder_first_run(self) -> None:
        messagebox.showinfo(
            "Bem-vindo",
            "Escolha a pasta onde os vídeos e o histórico serão gravados.\n\n"
            "Tudo fica nessa mesma pasta, e você pode trocá-la depois em \"Escolher…\".",
            parent=self,
        )
        if not self.choose_folder():
            # Cancelou: mantém a pasta padrão e não pergunta de novo.
            self._save_settings()

    # ------------------------------------------------------------------ layout

    def _build_styles(self) -> None:
        style = ttk.Style(self)
        family = tkfont.nametofont("TkDefaultFont").actual("family")
        style.configure("Card.TFrame", background="#ffffff", relief="solid", borderwidth=1)
        style.configure("CardTitle.TLabel", background="#ffffff", foreground="#6b6b6b", font=(family, 9))
        style.configure("CardValue.TLabel", background="#ffffff", font=(family, 15, "bold"))
        style.configure("Muted.TLabel", foreground="#6b6b6b")
        style.configure("Accent.TButton", font=(family, 10, "bold"), padding=(14, 4))
        style.configure("Treeview", rowheight=24)

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=12)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(3, weight=1)

        self._build_destination(root).grid(row=0, column=0, sticky="ew")
        self._build_stats(root).grid(row=1, column=0, sticky="ew", pady=10)
        self._build_links(root).grid(row=2, column=0, sticky="ew")

        self.notebook = ttk.Notebook(root)
        self.notebook.grid(row=3, column=0, sticky="nsew", pady=(10, 0))
        self.queue_tab = self._build_queue_tab(self.notebook)
        self.history_tab = self._build_history_tab(self.notebook)
        self.notebook.add(self.queue_tab, text="  Fila atual  ")
        self.notebook.add(self.history_tab, text="  Últimos salvamentos  ")

    def _build_destination(self, parent: ttk.Frame) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(parent, text="Pasta de destino (vídeos e histórico)", padding=8)
        frame.columnconfigure(0, weight=1)
        self.folder_var = tk.StringVar(value=self.settings.download_dir)
        ttk.Entry(frame, textvariable=self.folder_var, state="readonly").grid(row=0, column=0, sticky="ew")
        self.choose_btn = ttk.Button(frame, text="Escolher…", command=self.choose_folder)
        self.choose_btn.grid(row=0, column=1, padx=(8, 0))
        ttk.Button(frame, text="Abrir pasta", command=self.open_download_folder).grid(row=0, column=2, padx=(8, 0))
        return frame

    def _build_stats(self, parent: ttk.Frame) -> ttk.Frame:
        frame = ttk.Frame(parent)
        self.stat_vars: dict[str, tk.StringVar] = {}
        cards = [
            ("saved", "Downloads concluídos"),
            ("rate", "Taxa de sucesso"),
            ("size", "Total baixado"),
            ("last", "Último salvamento"),
        ]
        for column, (key, label) in enumerate(cards):
            frame.columnconfigure(column, weight=1, uniform="stats")
            card = ttk.Frame(frame, style="Card.TFrame", padding=(12, 8))
            card.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 8, 0))
            ttk.Label(card, text=label, style="CardTitle.TLabel").pack(anchor="w")
            var = tk.StringVar(value="—")
            ttk.Label(card, textvariable=var, style="CardValue.TLabel").pack(anchor="w")
            self.stat_vars[key] = var
        return frame

    def _build_links(self, parent: ttk.Frame) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(
            parent, text="Links do Instagram — um por linha (posts, reels, IGTV, carrosséis)", padding=8
        )
        frame.columnconfigure(0, weight=1)

        self.links_text = tk.Text(frame, height=6, wrap="none", font=("Consolas", 10), undo=True)
        self.links_text.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.links_text.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.links_text.configure(yscrollcommand=scroll.set)

        side = ttk.Frame(frame)
        side.grid(row=0, column=2, sticky="n", padx=(8, 0))
        ttk.Button(side, text="Colar", command=self.paste_links).pack(fill="x")
        ttk.Button(side, text="Importar .txt…", command=self.import_links).pack(fill="x", pady=4)
        ttk.Button(side, text="Limpar", command=lambda: self.links_text.delete("1.0", "end")).pack(fill="x")

        options = ttk.Frame(frame)
        options.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        options.columnconfigure(5, weight=1)

        ttk.Label(options, text="Downloads simultâneos:").grid(row=0, column=0)
        self.workers_var = tk.IntVar(value=self.settings.max_workers)
        self.workers_spin = ttk.Spinbox(
            options, from_=1, to=MAX_WORKERS, width=4, textvariable=self.workers_var, state="readonly"
        )
        self.workers_spin.grid(row=0, column=1, padx=(4, 16))

        ttk.Label(options, text="Cookies (login):").grid(row=0, column=2)
        self.cookie_var = tk.StringVar(value=self._cookie_label())
        self.cookie_combo = ttk.Combobox(
            options,
            textvariable=self.cookie_var,
            values=[*COOKIE_BROWSERS, COOKIE_FILE_LABEL],
            state="readonly",
            width=20,
        )
        self.cookie_combo.grid(row=0, column=3, padx=(4, 16))
        self.cookie_combo.bind("<<ComboboxSelected>>", self._on_cookie_source)

        self.skip_var = tk.BooleanVar(value=self.settings.skip_existing)
        self.skip_check = ttk.Checkbutton(options, text="Pular vídeos já baixados", variable=self.skip_var)
        self.skip_check.grid(row=0, column=4)

        self.cancel_btn = ttk.Button(options, text="Cancelar", command=self.cancel_downloads, state="disabled")
        self.cancel_btn.grid(row=0, column=6, padx=(8, 0))
        self.start_btn = ttk.Button(options, text="Baixar", style="Accent.TButton", command=self.start_downloads)
        self.start_btn.grid(row=0, column=7, padx=(8, 0))

        self.links_info = ttk.Label(frame, style="Muted.TLabel")
        self.links_info.grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))
        self._update_hint()
        return frame

    def _build_queue_tab(self, parent: ttk.Notebook) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=8)
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)

        overall = ttk.Frame(tab)
        overall.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        overall.columnconfigure(1, weight=1)
        ttk.Label(overall, text="Progresso geral:").grid(row=0, column=0, padx=(0, 8))
        self.overall_bar = ttk.Progressbar(overall, maximum=100)
        self.overall_bar.grid(row=0, column=1, sticky="ew")
        self.overall_var = tk.StringVar(value="Nenhum download em andamento.")
        ttk.Label(overall, textvariable=self.overall_var).grid(row=0, column=2, padx=(8, 0))

        columns = ("status", "progress", "speed", "title", "url")
        self.queue_tree = ttk.Treeview(tab, columns=columns, show="headings", selectmode="browse")
        for column, heading, width, stretch in [
            ("status", "Status", 110, False),
            ("progress", "Progresso", 90, False),
            ("speed", "Velocidade", 100, False),
            ("title", "Legenda / título", 380, True),
            ("url", "Link", 330, True),
        ]:
            self.queue_tree.heading(column, text=heading, anchor="w")
            self.queue_tree.column(column, width=width, stretch=stretch, anchor="w")
        self._configure_tags(self.queue_tree)
        self.queue_tree.grid(row=1, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(tab, orient="vertical", command=self.queue_tree.yview)
        scroll.grid(row=1, column=1, sticky="ns")
        self.queue_tree.configure(yscrollcommand=scroll.set)
        self.queue_tree.bind("<<TreeviewSelect>>", lambda _e: self._show_job_detail())
        self.queue_tree.bind("<Double-1>", lambda _e: self._open_selected_job())

        bottom = ttk.Frame(tab)
        bottom.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        bottom.columnconfigure(0, weight=1)
        self.queue_detail = ttk.Label(bottom, style="Muted.TLabel", wraplength=850, justify="left")
        self.queue_detail.grid(row=0, column=0, sticky="w")
        ttk.Button(bottom, text="Abrir arquivo", command=self._open_selected_job).grid(row=0, column=1, padx=6)
        ttk.Button(bottom, text="Mostrar na pasta", command=self._reveal_selected_job).grid(row=0, column=2)
        return tab

    def _build_history_tab(self, parent: ttk.Notebook) -> ttk.Frame:
        tab = ttk.Frame(parent, padding=8)
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)

        columns = ("date", "status", "uploader", "title", "size", "files")
        self.history_tree = ttk.Treeview(tab, columns=columns, show="headings", selectmode="browse")
        for column, heading, width, stretch in [
            ("date", "Data", 130, False),
            ("status", "Status", 80, False),
            ("uploader", "Perfil", 140, False),
            ("title", "Legenda / título", 360, True),
            ("size", "Tamanho", 90, False),
            ("files", "Arquivo(s)", 260, True),
        ]:
            self.history_tree.heading(column, text=heading, anchor="w")
            self.history_tree.column(column, width=width, stretch=stretch, anchor="w")
        self._configure_tags(self.history_tree)
        self.history_tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(tab, orient="vertical", command=self.history_tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.history_tree.configure(yscrollcommand=scroll.set)
        self.history_tree.bind("<Double-1>", lambda _e: self._open_history_file())

        buttons = ttk.Frame(tab)
        buttons.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(buttons, text="Abrir arquivo", command=self._open_history_file).pack(side="left")
        ttk.Button(buttons, text="Mostrar na pasta", command=self._reveal_history_file).pack(side="left", padx=6)
        ttk.Button(buttons, text="Abrir no Instagram", command=self._open_history_url).pack(side="left")
        ttk.Button(buttons, text="Adicionar à lista de links", command=self._requeue_history).pack(
            side="left", padx=6
        )
        ttk.Button(buttons, text="Limpar histórico", command=self._clear_history).pack(side="right")
        return tab

    @staticmethod
    def _configure_tags(tree: ttk.Treeview) -> None:
        tree.tag_configure("ok", foreground="#1a7f37")
        tree.tag_configure("error", foreground="#c62828")
        tree.tag_configure("muted", foreground="#7a7a7a")

    # ---------------------------------------------------------------- settings

    def _cookie_label(self) -> str:
        if self.settings.cookies_file:
            return COOKIE_FILE_LABEL
        for label, browser in COOKIE_BROWSERS.items():
            if browser == self.settings.cookies_browser:
                return label
        return "Nenhum"

    def _on_cookie_source(self, _event: object = None) -> None:
        label = self.cookie_var.get()
        if label == COOKIE_FILE_LABEL:
            path = filedialog.askopenfilename(
                parent=self,
                title="Selecione o arquivo cookies.txt (formato Netscape)",
                filetypes=[("Cookies", "*.txt"), ("Todos os arquivos", "*.*")],
            )
            if not path:
                self.cookie_var.set(self._cookie_label())
                return
            self.settings.cookies_file, self.settings.cookies_browser = path, ""
        else:
            self.settings.cookies_file, self.settings.cookies_browser = "", COOKIE_BROWSERS[label]
        self._save_settings()
        self._update_hint()

    def _update_hint(self, prefix: str = "") -> None:
        hints = [prefix] if prefix else []
        if self.settings.cookies_file:
            hints.append(f"Usando cookies de: {Path(self.settings.cookies_file).name}.")
        elif not self.settings.cookies_browser:
            hints.append(
                "O Instagram costuma exigir login: escolha os cookies de um navegador logado "
                "(no Windows, o Firefox é o mais confiável)."
            )
        if not ffmpeg_available():
            hints.append("ffmpeg não encontrado: será baixado o melhor arquivo único disponível.")
        self.links_info.configure(text="  ".join(hints))

    def _save_settings(self) -> None:
        self.settings.max_workers = min(max(int(self.workers_var.get() or 1), 1), MAX_WORKERS)
        self.settings.skip_existing = bool(self.skip_var.get())
        try:
            self.settings.save()
        except OSError as exc:
            messagebox.showwarning("Configurações", f"Não foi possível salvar as configurações:\n{exc}", parent=self)

    def choose_folder(self) -> bool:
        """Pede a pasta de destino ao usuário. Retorna True se uma pasta válida foi escolhida."""
        while True:
            path = filedialog.askdirectory(
                parent=self,
                title="Escolha onde gravar os vídeos e o histórico",
                initialdir=self.settings.download_dir if Path(self.settings.download_dir).is_dir() else Path.home(),
            )
            if not path:
                return False
            folder = Path(path).resolve()
            if not is_inside(folder, APP_ROOT):
                break
            messagebox.showerror(
                "Pasta não permitida",
                "Essa pasta fica dentro do repositório do aplicativo.\n\n"
                "Para que vídeos e histórico não acabem no GitHub, escolha uma pasta fora de:\n"
                f"{APP_ROOT}",
                parent=self,
            )
        self.settings.download_dir = str(folder)
        self.folder_var.set(str(folder))
        self.history = History(folder)
        self._save_settings()
        self.refresh_history()
        return True

    def open_download_folder(self) -> None:
        folder = Path(self.settings.download_dir)
        folder.mkdir(parents=True, exist_ok=True)
        open_path(folder)

    # ------------------------------------------------------------------ links

    def _append_links(self, text: str) -> None:
        current = self.links_text.get("1.0", "end").strip()
        self.links_text.insert("end", ("\n" if current else "") + text.strip() + "\n")
        self.links_text.see("end")

    def paste_links(self) -> None:
        try:
            self._append_links(self.clipboard_get())
        except tk.TclError:
            pass

    def import_links(self) -> None:
        path = filedialog.askopenfilename(
            parent=self, title="Importar lista de links", filetypes=[("Texto", "*.txt"), ("Todos", "*.*")]
        )
        if path:
            self._append_links(Path(path).read_text(encoding="utf-8", errors="replace"))

    # -------------------------------------------------------------- downloads

    def start_downloads(self) -> None:
        if self.manager and self.manager.running:
            return
        urls, invalid = parse_sources(self.links_text.get("1.0", "end"))
        if not urls:
            messagebox.showwarning("Nenhum link", "Cole pelo menos um link válido do Instagram.", parent=self)
            return
        self._save_settings()
        try:
            Path(self.settings.download_dir).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("Pasta de destino", f"Não foi possível criar a pasta:\n{exc}", parent=self)
            return

        self.jobs = {index: Job(index, url) for index, url in enumerate(urls, start=1)}
        self.queue_tree.delete(*self.queue_tree.get_children())
        for job in self.jobs.values():
            self.queue_tree.insert("", "end", iid=str(job.id), values=self._job_values(job))
        self.queue_detail.configure(text="")

        self.manager = DownloadManager(
            dataclasses.replace(self.settings),
            self.history,
            on_job_update=lambda job: self._events.put(("job", job)),
            on_finished=lambda: self._events.put(("finished", None)),
        )
        self.manager.start(self.jobs.values())
        self._set_running(True)
        self.notebook.select(self.queue_tab)
        self._update_overall()

        prefix = f"{len(urls)} link(s) adicionados à fila."
        if invalid:
            prefix += f" {len(invalid)} trecho(s) ignorado(s) por não serem links do Instagram."
        self._update_hint(prefix)

    def cancel_downloads(self) -> None:
        if self.manager:
            self.manager.cancel()
            self.cancel_btn.configure(state="disabled")
            self.overall_var.set("Cancelando…")

    def _set_running(self, running: bool) -> None:
        self.start_btn.configure(state="disabled" if running else "normal")
        self.cancel_btn.configure(state="normal" if running else "disabled")
        self.choose_btn.configure(state="disabled" if running else "normal")
        self.workers_spin.configure(state="disabled" if running else "readonly")
        self.cookie_combo.configure(state="disabled" if running else "readonly")
        self.skip_check.configure(state="disabled" if running else "normal")

    def _poll_events(self) -> None:
        changed: dict[int, Job] = {}
        batch_finished = False
        try:
            while True:
                kind, payload = self._events.get_nowait()
                if kind == "job":
                    changed[payload.id] = payload
                else:
                    batch_finished = True
        except queue.Empty:
            pass

        for job in changed.values():
            if self.queue_tree.exists(str(job.id)):
                self.queue_tree.item(str(job.id), values=self._job_values(job), tags=self._job_tags(job))
        if changed:
            self._update_overall()
            self._show_job_detail()
            if any(job.status.finished for job in changed.values()):
                self.refresh_history()
        if batch_finished:
            self._on_batch_finished()
        self.after(150, self._poll_events)

    @staticmethod
    def _job_values(job: Job) -> tuple:
        return (job.status.value, f"{job.progress:.0%}", job.speed, job.title, job.url)

    @staticmethod
    def _job_tags(job: Job) -> tuple:
        tag = STATUS_TAGS.get(job.status)
        return (tag,) if tag else ()

    def _update_overall(self) -> None:
        jobs = list(self.jobs.values())
        if not jobs:
            return
        progress = sum(1.0 if job.status.finished else job.progress for job in jobs) / len(jobs)
        self.overall_bar["value"] = progress * 100
        counts = {status: sum(job.status is status for job in jobs) for status in JobStatus}
        finished = sum(counts[status] for status in JobStatus if status.finished)
        parts = [f"{finished}/{len(jobs)} finalizados ({finished / len(jobs):.0%})", f"{counts[JobStatus.DONE]} ok"]
        if counts[JobStatus.FAILED]:
            parts.append(f"{counts[JobStatus.FAILED]} com erro")
        if counts[JobStatus.SKIPPED]:
            parts.append(f"{counts[JobStatus.SKIPPED]} já baixados")
        if counts[JobStatus.CANCELLED]:
            parts.append(f"{counts[JobStatus.CANCELLED]} cancelados")
        self.overall_var.set(" • ".join(parts))

    def _on_batch_finished(self) -> None:
        self._set_running(False)
        self._update_overall()
        self.refresh_history()
        self.bell()

    def _selected_job(self) -> Job | None:
        selection = self.queue_tree.selection()
        return self.jobs.get(int(selection[0])) if selection else None

    def _show_job_detail(self) -> None:
        job = self._selected_job()
        if job is None:
            return
        if job.error:
            text = f"{job.status.value}: {job.error}"
        elif job.files:
            text = "Salvo em: " + " | ".join(job.files)
        else:
            text = job.url
        self.queue_detail.configure(text=text)

    def _selected_job_file(self) -> str | None:
        job = self._selected_job()
        existing = [f for f in job.files if os.path.exists(f)] if job else []
        return existing[0] if existing else None

    def _open_selected_job(self) -> None:
        if path := self._selected_job_file():
            open_path(path)

    def _reveal_selected_job(self) -> None:
        if path := self._selected_job_file():
            reveal_in_folder(path)

    # ---------------------------------------------------------------- history

    def refresh_history(self) -> None:
        stats = self.history.stats()
        self.stat_vars["saved"].set(f"{stats.successes}  ({stats.files} arquivo{'s' if stats.files != 1 else ''})")
        rate = stats.success_rate
        self.stat_vars["rate"].set("—" if rate is None else f"{rate:.0%}  ({stats.failures} falha(s))")
        self.stat_vars["size"].set(format_size(stats.total_bytes))
        self.stat_vars["last"].set(
            stats.last_success.date.strftime("%d/%m/%Y %H:%M") if stats.last_success else "—"
        )

        self._history_rows = self.history.recent()
        self.history_tree.delete(*self.history_tree.get_children())
        for index, entry in enumerate(self._history_rows):
            files = ", ".join(Path(f).name for f in entry.files) if entry.ok else entry.error
            self.history_tree.insert(
                "",
                "end",
                iid=str(index),
                tags=("ok" if entry.ok else "error",),
                values=(
                    entry.date.strftime("%d/%m/%Y %H:%M"),
                    "✔ Salvo" if entry.ok else "✖ Erro",
                    entry.uploader,
                    entry.title,
                    format_size(entry.size_bytes) if entry.ok else "",
                    files,
                ),
            )

    def _selected_history(self) -> HistoryEntry | None:
        selection = self.history_tree.selection()
        return self._history_rows[int(selection[0])] if selection else None

    def _selected_history_file(self) -> str | None:
        entry = self._selected_history()
        if entry is None:
            return None
        existing = [f for f in entry.files if os.path.exists(f)]
        if not existing:
            messagebox.showinfo("Arquivo", "O arquivo não existe mais (foi movido ou apagado).", parent=self)
            return None
        return existing[0]

    def _open_history_file(self) -> None:
        if path := self._selected_history_file():
            open_path(path)

    def _reveal_history_file(self) -> None:
        if path := self._selected_history_file():
            reveal_in_folder(path)

    def _open_history_url(self) -> None:
        if entry := self._selected_history():
            webbrowser.open(entry.url)

    def _requeue_history(self) -> None:
        if entry := self._selected_history():
            self._append_links(entry.url)

    def _clear_history(self) -> None:
        if messagebox.askyesno(
            "Limpar histórico",
            "Apagar o histórico de downloads?\nOs vídeos já baixados não serão apagados.",
            parent=self,
        ):
            self.history.clear()
            self.refresh_history()

    # ------------------------------------------------------------------ close

    def _on_close(self) -> None:
        if self.manager and self.manager.running:
            if not messagebox.askyesno(
                "Sair", "Há downloads em andamento. Deseja cancelá-los e sair?", parent=self
            ):
                return
            self.manager.cancel()
        self._save_settings()
        self.destroy()


def main() -> None:
    if sys.platform == "win32":
        try:  # textos nítidos em telas com escala (DPI alto)
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    App().mainloop()
