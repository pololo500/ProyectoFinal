# Servidor PC: TTS CosyVoice 2 — diseño

Fecha: 2026-09-13  
Producto: peluche TEO + `ServidorDePC/`  
Estado: aprobado en conversación (recorte 1,28–6,06 s + prueba de escritorio)  
Supersede parcial: en `2026-09-13-pc-server-tts-chatterbox-design.md`, el motor Chatterbox queda fuera. HTTP, Pi, Piper y circuit TTS **no se reabren**.

## Problema

Chatterbox multilingual en CPU tardó 45,7 s para 3,68 s de audio. El contrato Pi (`POST /v1/audio/speech` → WAV) está bien; el motor no.

## Objetivo

1. Windows sintetiza con **CosyVoice 2.0** (`FunAudioLLM/CosyVoice2-0.5B`), zero-shot, clip rioplatense recortado.
2. Misma API y fallback Piper. La Pi no cambia.
3. Prueba de escritorio: una frase típica de Teo, oír el WAV y medir tiempo de punta a punta.
4. 100 % local. Sin Edge/Azure.

## Clip

Fuente: `voices/teo_es_ar.wav` (16,5 s, 44,1 kHz estéreo).  
Uso: `voices/teo_es_ar_prompt.wav` recorte **1,28–6,06 s** + `voices/teo_es_ar_prompt.txt`:

> Es más, me abre la posibilidad de usar mi segundo color. Mi color favorito es el azul.

Sin WAV o sin TXT → `tts.ready=false`.

## Motor

- Repo: clone `--recursive` de FunAudioLLM/CosyVoice en `ServidorDePC/third_party/CosyVoice` (gitignore).
- Pesos: `pretrained_models/CosyVoice2-0.5B` (gitignore).
- API: `CosyVoice2` / `AutoModel`, `inference_zero_shot(tts_text, prompt_text, prompt_wav, stream=False)`, `fp16` si hay CUDA.
- **No** instalar `requirements.txt` oficial de CosyVoice: pinea `torch==2.3.1` y rompe RTX 5080. Deps mínimas en `requirements-tts.txt` **sin** pin de torch.
- Torch CUDA (cu124/cu128) se reinstala aparte, como el LLM.
- Windows: `wetext` (no ttsfrd). Sin DeepSpeed/TensorRT.

## Fuera de alcance

Streaming WebSocket, CosyVoice 3, LoRA, cambiar timeouts de la Pi, Chatterbox como segundo motor.

## Criterio de hecho

- `TtsEngine.synthesize` devuelve WAV; log `[TTS] CosyVoice2 listo`.
- Probe de escritorio: frase de Teo, tiempo de reloj y archivo audible.
- Tests de handlers/health sin GPU siguen verdes.
