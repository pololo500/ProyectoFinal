@echo off
setlocal enabledelayedexpansion

cd /d %~dp0

set "PYTHON_EXE="

if exist "C:\python313\python.exe" (
    set "PYTHON_EXE=C:\python313\python.exe"
) else (
    where py >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_EXE=py -3"
    ) else (
        where python >nul 2>nul
        if not errorlevel 1 (
            set "PYTHON_EXE=python"
        )
    )
)

if not defined PYTHON_EXE (
    echo No se encontro ningun interprete de Python.
    exit /b 1
)

if not exist .venv (
    echo No se encontro .venv. Si quieres usar un entorno aislado, crealo antes de ejecutar este BAT.
)

if not exist dist mkdir dist
if not exist build mkdir build

call %PYTHON_EXE% -m pip install --upgrade pip
call %PYTHON_EXE% -m pip install -r requirements.txt
call %PYTHON_EXE% -m pip install pyinstaller

for /f "delims=" %%A in ('%PYTHON_EXE% -c "import numpy as np, os; print(os.path.join(os.path.dirname(np.__file__), '.libs'))"') do set "NUMPY_LIBS=%%A"

set "NUMPY_ADD_BINARY="
if defined NUMPY_LIBS (
    if exist "%NUMPY_LIBS%" (
        set "NUMPY_ADD_BINARY=--add-binary "%NUMPY_LIBS%\*;numpy.\libs""
    )
)

call %PYTHON_EXE% -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --console ^
    --name EdgeAIPoC ^
    --add-data "intent_rules.json;." ^
    --hidden-import cv2 ^
    --hidden-import mediapipe ^
    --hidden-import PIL ^
    --hidden-import sounddevice ^
    --hidden-import spacy ^
    --hidden-import scrubadub ^
    --hidden-import faster_whisper ^
    --hidden-import numpy ^
    app.py

if errorlevel 1 (
    echo.
    echo Fallo la generacion del ejecutable.
    exit /b 1
)

echo.
echo Ejecutable generado en dist\EdgeAIPoC.exe
endlocal