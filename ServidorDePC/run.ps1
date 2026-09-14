# Arranque del servidor TEO en Windows (RTX 5080).
# Ejecutar en PowerShell como administrador la primera vez (firewall).
# Usá Python 3.12 (py -3.12). El `python` del PATH puede ser 3.14; los wheels
# CUDA de llama-cpp-python cubren 3.10–3.12.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Invoke-Py312 {
    param([Parameter(Mandatory = $true)][string[]]$PyArgs)
    & py -3.12 @PyArgs
    if ($LASTEXITCODE -ne 0) {
        throw "py -3.12 $($PyArgs -join ' ') fallo exit=$LASTEXITCODE"
    }
}

Write-Host "Python 3.12:"
Invoke-Py312 @("--version")

Write-Host "Comprobando NVIDIA..."
nvidia-smi | Select-Object -First 8

$ruleName = "TEO ServidorDePC 8090"
$existing = netsh advfirewall firewall show rule name="$ruleName" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Creando regla de firewall inbound TCP 8090 (redes privadas)..."
    netsh advfirewall firewall add rule name="$ruleName" dir=in action=allow protocol=TCP localport=8090 profile=private
}

Write-Host "Evitá que Windows duerma mientras corre el servidor (Configuración > Energía)."
if (-not $env:PC_SERVER_TOKEN) {
    Write-Host "Si no hay PC_SERVER_TOKEN, se crea pc_server_token.txt. Copiá ese valor a la Pi (PC_SERVER_TOKEN)."
}

Write-Host "Instalando FastAPI / numpy / faster-whisper (sin llama-cpp)..."
Invoke-Py312 @("-m", "pip", "install", "-r", "requirements.txt", "--no-cache-dir")

Write-Host "Instalando Piper + Elena (requirements-tts.txt)..."
$prev = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& py -3.12 -m pip install -r requirements-tts.txt --no-cache-dir
if ($LASTEXITCODE -ne 0) {
    Write-Host "TTS deps no se instalaron; /health dejara tts=false y la Pi usa Piper local."
}
$ErrorActionPreference = $prev

function Install-LlamaCppWheel([string]$CudaTag) {
    Write-Host "Intentando llama-cpp-python wheel $CudaTag (only-binary, sin compile)..."
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & py -3.12 -m pip install "llama-cpp-python>=0.3.0" `
        --only-binary=:all: `
        --prefer-binary `
        --extra-index-url "https://abetlen.github.io/llama-cpp-python/whl/$CudaTag" `
        --no-cache-dir
    $ok = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = $prev
    return $ok
}

$llmOk = $false
# No hay cu128 oficial. cu125 primero; cu124 es el ejemplo del plan.
foreach ($tag in @("cu125", "cu124")) {
    if (Install-LlamaCppWheel $tag) {
        $llmOk = $true
        Write-Host "llama-cpp-python CUDA $tag instalado."
        break
    }
}

if (-not $llmOk) {
    Write-Host @"
No se instalo llama-cpp-python (no se compiló a propósito: el sdist de PyPI
rompe cmake por hash mismatch y deja sin numpy).

Plan B RTX 5080 / Blackwell sm_120:
  1. Instalar llama.cpp CUDA 12.8+ (release oficial o build con GGML_CUDA).
  2. Arrancar llama-server -ngl 99 --port 8081 --api-key <token>
  3. FastAPI sigue con Whisper; el chat proxea a llama-server.
El resto de deps ya esta; STT puede funcionar igual.
"@
}

Invoke-Py312 @("server.py")
