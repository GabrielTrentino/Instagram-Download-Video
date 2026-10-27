@echo off
rem Cria o ambiente virtual (na primeira vez), atualiza o yt-dlp e abre o aplicativo.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Criando ambiente virtual...
    python -m venv .venv || (
        echo Python nao encontrado. Instale em https://www.python.org/downloads/
        pause
        exit /b 1
    )
)

echo Verificando dependencias...
".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check --upgrade -r requirements.txt

start "" ".venv\Scripts\pythonw.exe" main.py
