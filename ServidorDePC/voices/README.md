# Voz de referencia de TEO (CosyVoice 2)

Copiá el WAV largo a `teo_es_ar.wav` (no se sube a git). El motor usa el recorte:

- `teo_es_ar_prompt.wav` — 1,28–6,06 s del original
- `teo_es_ar_prompt.txt` — transcript de ese recorte

Sin esos dos archivos el `/health` deja `"tts": false` y la Pi habla con Piper.

No uses un clip generado con Piper: el clon arrastra la voz robótica.
