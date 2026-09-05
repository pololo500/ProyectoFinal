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
    python3-dev \
    python3-lgpio \
    liblgpio-dev \
    python3-spidev \
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
uv pip install vosk || echo "  Aviso: vosk no se instaló. En el venv: uv pip install vosk"

# GPIO / SPI (Raspberry Pi 5: lgpio + spidev para servos, pulsador y LCD ST7789)
echo "[4b/5] Habilitando SPI e instalando lgpio/spidev..."
if command -v raspi-config >/dev/null; then
    sudo raspi-config nonint do_spi 0 || true
fi
if command -v usermod >/dev/null; then
    sudo usermod -aG spi,gpio "$USER" 2>/dev/null || true
fi
uv pip install lgpio spidev || echo "  Aviso: lgpio/spidev no se instalaron. En la Pi: sudo apt install python3-lgpio python3-spidev"

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
if command -v getconf >/dev/null; then
    PAGE_SIZE="$(getconf PAGE_SIZE 2>/dev/null || getconf PAGESIZE 2>/dev/null || echo "")"
    if [ "$PAGE_SIZE" = "16384" ]; then
        echo " AVISO: esta Pi usa páginas de 16K. faster-whisper pega Bus error."
        echo " Antes de python app.py, pasá el kernel a 4K y reiniciá:"
        echo "   sudo sed -i '1i kernel=kernel8.img' /boot/firmware/config.txt"
        echo "   sudo reboot"
        echo " Después: getconf PAGE_SIZE  →  debe ser 4096"
        echo ""
    fi
fi
echo " Para ejecutar la aplicación:"
echo " 1. Activa el entorno: source venv/bin/activate"
echo " 2. Ejecuta la app: python app.py"
echo "===================================================="
