"""Ponto de entrada: python main.py"""

import sys

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
