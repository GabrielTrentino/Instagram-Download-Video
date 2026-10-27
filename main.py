"""Ponto de entrada: python main.py"""

import os
import sys

# Executável sem console (pythonw/PyInstaller --windowed) não tem stdout/stderr, e o yt-dlp
# escreve neles em alguns casos.
for _name in ("stdout", "stderr"):
    if getattr(sys, _name) is None:
        setattr(sys, _name, open(os.devnull, "w", encoding="utf-8"))

try:
    from insta_downloader.gui import main
except ModuleNotFoundError as exc:
    if exc.name != "yt_dlp":
        raise
    import tkinter.messagebox

    tkinter.messagebox.showerror(
        "Dependência ausente",
        "O pacote yt-dlp não está instalado.\n\nExecute:  pip install -r requirements.txt\n"
        "(ou use o iniciar.bat, que instala tudo automaticamente).",
    )
    sys.exit(1)

if __name__ == "__main__":
    main()
