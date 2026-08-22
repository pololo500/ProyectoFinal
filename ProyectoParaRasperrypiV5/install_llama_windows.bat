@echo off
REM Instala llama-cpp-python en Windows evitando el error MAX_PATH del sdist.
REM Usa wheels precompilados (CPU). Si no hay wheel, TEMP corto + rutas largas.

setlocal
cd /d "%~dp0"

if not exist C:\t mkdir C:\t
set "TEMP=C:\t"
set "TMP=C:\t"

echo [1/2] Wheel precompilado CPU...
python -m pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
if %ERRORLEVEL%==0 goto :ok

echo [2/2] Fallback: instalar desde fuente con TEMP corto...
python -m pip install llama-cpp-python --no-cache-dir
if %ERRORLEVEL%==0 goto :ok

echo.
echo FALLO. Activa rutas largas (Admin) y reintenta:
echo   New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name "LongPathsEnabled" -Value 1 -PropertyType DWORD -Force
exit /b 1

:ok
python -c "from llama_cpp import Llama; print('llama-cpp-python OK')"
exit /b 0
