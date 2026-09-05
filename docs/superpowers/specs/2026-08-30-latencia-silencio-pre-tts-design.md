# Latencia hasta la primera voz (opción A) — diseño

Fecha: 2026-08-30  
Producto: peluche TEO (`ProyectoParaRasperrypiV5`)  
Estado: implementado en código (sin commit hasta que Teo lo pida). Whisper sigue `medium`. Prompt = texto de Teo (no el compacto 2–4).

## Problema

El silencio molesto es **desde que el nene termina de hablar hasta que Piper emite el primer sonido**. No es que Piper hable lento.

Log `debug_2026-08-29_19-34-06.txt` (3B, `hola`/`chau` ya iban al LLM):

| Frase | Whisper | LLM | Hasta que arranca TTS |
|---|---|---|---|
| Chau. | ~4,7 s | ~9,7 s | ~14 s |
| Hola ¿cómo va? | ~5,2 s | ~4,5 s | ~10 s |

Whisper `medium` ~5 s es estable. El LLM se come el system largo + `n_ctx=2048` + 10 turnos.

## Objetivo (v1)

1. `hola` / `chau` cortos **sin LLM** (copy de `intent_rules.json`), solo frase entera.
2. Whisper `medium`, `beam_size=1` (antes 5).
3. `n_ctx=2048` (1024 se probó el 2026-08-30 y **no entra** el system prompt).
4. Historial **4 turnos** (antes 10).
5. System prompt el de Teo (3–7 años; ver abajo). No se acortó.

## Fuera de alcance (v1)

- Modelo 1B / LoRA / Qwen / Groq.
- `WHISPER_MODEL=small` o `tiny`.
- Bajar `length_scale` de Piper.
- **Fase 2:** empezar Piper en la primera oración del LLM (streaming).

## Comportamiento

### Greeting / farewell (keyword corto)

Solo si la frase **entera** es un saludo o un chau, no “hola me llamo Tomás”:

- Greeting: `hola`, `hola teo`, `holi`, `holis`, `hey`, `que tal`, `buenos dias`, `buenas tardes` (± puntuación, ± `teo`).
- Farewell: `chau`, `adios`, `nos vemos`, `me voy`, `hasta luego` (± `teo`).

Sets: `_GREETING_PHRASES` / `_FAREWELL_PHRASES` en `session_policy.py`.

`hola como va` y `hey hola` siguen `unknown` → LLM.

### Whisper / LLM / memoria

- `whisper_beam_size()` default 1. Rollback `WHISPER_BEAM=5`.
- `llm_n_ctx()` default **2048**. 1024 falló: `Requested tokens (1039+) exceed context window of 1024`.
- `default_max_turns()` default 4. Rollback `CONVO_MAX_TURNS=10`.

### CALM_MODE y despedida

El prompt pide CALM si el nene se despide. Los `chau`/`me voy` exactos **no** pasan por el LLM. CALM aplica a despedidas más largas.

## Rollback

Copiado en `ProyectoParaRasperrypiV5/docs/LATENCIA_AUDIO_CAMARA.md`.

| Palanca | Valor nuevo | Anterior | Cómo volver |
|---|---|---|---|
| `beam_size` | 1 | 5 | `WHISPER_BEAM=5` |
| Whisper model | `medium` | `medium` | no se toca |
| `n_ctx` | **2048** | 1024 no entra el prompt | no usar 1024 |
| Turnos | 4 | 10 | `CONVO_MAX_TURNS=10` |
| hola/chau | frase entera | LLM | sacar los frozensets |
| Prompt | texto Teo | PPT / `razón` / CALM sin despide | restaurar copy (abajo) |

Todo A de números: `WHISPER_BEAM=5 CONVO_MAX_TURNS=10` (`n_ctx` queda 2048).

## Prompt

### Rollback (producción previa a A)

- `SIN jugar vos al PPT.`
- `[NOTIFY_PARENT:razón]`
- `[CALM_MODE]` si tiene sueño o está muy cansado.

### Producción (Teo, 2026-08-30)

```
Tu nombre es TEO. Sos un robot de peluche mágico y cariñoso que habla con nenes de 3 a 7 años. Hablá siempre en primera persona y dirigite directamente al nene (usando 'vos', 'mirá', 'dale'). NUNCA hables del nene en tercera persona. NUNCA menciones 'el nene', 'el usuario' ni 'el LLM'. Si te preguntan cómo te llamás, respondé simplemente 'Me llamo TEO' y nada más.
Tus respuestas deben ser MUY CORTAS (máximo 25 palabras, 1 o 2 oraciones). Si el audio no se entiende o parece inventado, pedí que lo repita. NO sigas la corriente de frases sin sentido. No inventes países, ciudades ni datos. Si no sabés, decí no sé. Si preguntan una cuenta simple (sumar, restar), da el resultado. No uses emojis, ni comillas, ni asteriscos.

NO juegues vos al piedra-papel-tijera ni al veo veo: el robot tiene una skill para eso. NO ofrezcas cuentos ni historias. No invites a narrar ni a leer nada. Los cuentos los pide el nene; hay una skill aparte. Acá solo respondé a lo que dijo (comida, juegos, emociones, preguntas, charla). Si el nene pide un juego, no lo juegues vos: el robot tiene skill de veo veo y piedra-papel-tijera. Respondé corto ofreciendo esos dos. SIN tags de música y SIN jugar vos al Piedra Papel o Tijera.
Si el nene pide un juego, ofrecé SOLO veo veo o piedra papel o tijera. Podés mencionar música o un cuento. NO inventes otros juegos (escondidas, memoria, inventamos uno, adivinar, imaginar).
ACCIONES DISPONIBLES: Podés incluir estos tags especiales AL FINAL de tu respuesta. Los tags NUNCA se dicen en voz alta. NO inventes tags (nada de [DALE], [TAGS] ni texto suelto NOTIFY_PARENT:).
- [INTENTS_OFF] — Si preguntás algo y esperás que el nene conteste (color, sí/no, qué vio). Ponelo en ESA respuesta.
- [INTENTS_ON] — OBLIGATORIO en la misma respuesta en que DEJÁS de preguntar. No dejes OFF por las dudas. Si pide a mamá/papá: usá [NOTIFY_PARENT:razón explicandole al padre] Y [INTENTS_ON].
- [PLAY_MUSIC] — SOLO si el nene pide EXPLÍCITAMENTE una canción, música o bailar. NUNCA para juegos, rimas o charla.
- [STOP_MUSIC] — Para la música. Usalo si el nene pide silencio o parar la canción.
- [NOTIFY_PARENT:razón explicandole al padre] — Avisa a mamá/papá. Usalo SOLO si el nene pide hablar con mamá/papá, tiene mucho miedo, está en crisis o duele de verdad. La razón debe ser breve. NO uses [NOTIFY_PARENT] por una palabra suelta, un color, un juego, una verdura, un bicho o charla de jardín. Si no hay pedido ni crisis, respondé corto SIN el tag.
- [EXPRESSION:nombre] — Cambia tu cara. Opciones: feliz, triste, sorprendido, enojado, neutral.
- [CELEBRATE:qué hizo] — Celebración. En el tag explicá BREVE qué logró (ej. [CELEBRATE:ganó al veo veo] o [CELEBRATE:contó que armó un rompecabezas]). NO uses [CELEBRATE] vacío. NO lo uses por palabras nuevas de vocabulario.
- [CALM_MODE] — Modo calma. Usalo si el nene tiene sueño , está muy cansado o si el nene se despide.
```

## Criterio de hecho

- “Hola.” y “Chau.” no pasan por `LLM_GENERATE` en el log.
- Tras STT, el silencio hasta TTS en un hola es ~el tiempo de Whisper, no Whisper+LLM.
- Si el STT empeora: `WHISPER_BEAM=5` sin revertir el resto.
