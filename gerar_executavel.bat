@echo off
rem Gera dist\InstagramDownloader.exe (a pasta dist\ e os arquivos de build nao vao para o repositorio).
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Criando ambiente virtual...
    python -m venv .venv || (
        echo Python nao encontrado. Instale em https://www.python.org/downloads/
        pause
        exit /b 1
    )
)

echo Instalando dependencias...
".venv\Scripts\python.exe" -m pip install --quiet --disable-pip-version-check --upgrade -r requirements.txt pyinstaller || (
    pause
    exit /b 1
)

echo Gerando executavel...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --name InstagramDownloader --workpath build --specpath build --distpath dist main.py || (
    pause
    exit /b 1
)

echo.
echo Pronto: %~dp0dist\InstagramDownloader.exe
pause
