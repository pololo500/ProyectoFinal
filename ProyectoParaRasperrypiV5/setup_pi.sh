#!/usr/bin/env bash
set -e

echo "===================================================="
echo " Instalación de Dependencias para Raspberry Pi 5"
echo " Proyecto Edge AI Interactivo"
echo "===================================================="

# 1. Instalar paquetes esenciales del sistema
echo "[1/4] Instalando paquetes del sistema (apt)..."
sudo apt update
sudo apt install -y \
    python3-pip \
    python3-venv \
    build-essential \
    portaudio19-dev \
    libportaudio2 \
    ffmpeg \
    espeak-ng \
    libgl1 \
    libglib2.0-0 \
    libopenblas-dev \
    curl

# 2. Instalar uv de forma independiente (sin pip del sistema)
echo "[2/4] Instalando 'uv' para gestión de Python 3.11..."
if ! command -v uv &> /dev/null && [ ! -f "$HOME/.local/bin/uv" ]; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi

export PATH="$HOME/.local/bin:$PATH"

# 3. Crear entorno virtual con Python 3.11 (requerido por MediaPipe en ARM64)
echo "[3/4] Creando entorno virtual con Python 3.11..."
if [ -d "venv" ]; then
    rm -rf venv
fi

uv venv --python 3.11 venv
source venv/bin/activate

# 4. Instalar todas las dependencias en el entorno virtual
echo "[4/5] Instalando paquetes de Python (requirements.txt y spaCy)..."
uv pip install -r requirements.txt
python -m spacy download es_core_news_md

# 5. llama-cpp-python se compila desde source en ARM64 (~5 min en RPi 5).
#    Si la compilación falla, la app sigue funcionando sin el LLM de fallback.
echo "[5/5] Verificando llama-cpp-python (compilación C++ en ARM64, puede tardar ~5 min)..."
if ! python -c "from llama_cpp import Llama" 2>/dev/null; then
    echo "  Nota: llama-cpp-python no pudo cargarse. El LLM de fallback estará deshabilitado."
    echo "  La app funciona normalmente sin él."
fi

echo ""
echo "===================================================="
echo " ¡Instalación completada con éxito!"
echo ""
echo " Para ejecutar la aplicación:"
echo " 1. Activa el entorno: source venv/bin/activate"
echo " 2. Ejecuta la app: python app.py"
echo "===================================================="
