# Sprites PNG de ojos por emoción — diseño

Fecha: 2026-09-12  
Producto: peluche TEO (`ProyectoParaRasperrypiV5`)  
Estado: diseño aprobado en conversación; sin commit hasta que Teo lo pida

## Problema

Los ojos de la LCD ST7789 se dibujan en cada frame (elipses Pillow / canvas tkinter). No hay archivos de arte versionables. Mandar SVG no sirve: la pantalla espera un bitmap RGB565 320×240 y Pillow ya está en el proyecto.

Hace falta versionar expresiones como PNG y animarlas con una grilla de sprites, sin romper el peluche mientras faltan archivos.

## Objetivo

1. Cada emoción puede tener un PNG (grilla de celdas 320×240) y un JSON sidecar.
2. `set_expression("feliz")` no cambia: si hay sprites, se muestran; si no, se dibujan los ojos de hoy.
3. LCD y ventana tkinter muestran el mismo contenido cuando hay sprite.
4. Versionar es reemplazar `eyes/{emocion}.png` y/o `.json` y reiniciar la app.

## Fuera de alcance (v1)

- SVG / Cairo.
- Un atlas con todas las emociones.
- Frames sueltos (`feliz/00.png`).
- Recarga en caliente sin reiniciar.
- Editor de JSON o UI para elegir sprites.
- Parpadeo procedural encima de un sprite (la animación va en el PNG).
- Cambiar `app.py`, intents, GPIO o el driver SPI (`lcd.display` ya acepta PIL).

## Decisiones de formato

Celda fija: **320×240 px**, RGB. No se declara en el JSON. Coincide con la LCD en paisaje (`hardware_pins.json`: 240×320 nativa, rotación 90).

Un archivo por emoción, mismo stem que `set_expression`:

```
ProyectoParaRasperrypiV5/eyes/feliz.png
ProyectoParaRasperrypiV5/eyes/feliz.json
```

Emociones actuales (todas opcionales): `neutral`, `feliz`, `triste`, `sorprendido`, `enojado`, `escuchando`, `hablando`, `dormido`, `pensando`, `zzz`. Sin par PNG+JSON, esa emoción sigue procedural (`zzz` texto, `pensando` spinner).

Orden de frames: izquierda → derecha, arriba → abajo. Índice `i = row * columns + col`.

PNG con alpha: se aplana sobre el fondo actual `(26, 26, 46)` y queda RGB.

Ejemplo `eyes/feliz.json` para una grilla 4×2 (PNG 1280×480):

```json
{
  "columns": 4,
  "rows": 2,
  "fps": 12,
  "loop": true,
  "frame_count": 8
}
```

| Campo | Obligatorio | Regla |
|---|---|---|
| `columns` | sí | entero ≥ 1 |
| `rows` | sí | entero ≥ 1 |
| `fps` | sí | número > 0 |
| `loop` | no | default `true` |
| `frame_count` | no | default `columns * rows`; debe estar en `1 .. columns * rows` |

Tamaño del PNG debe ser exactamente `columns * 320` × `rows * 240`. Si no, esa emoción no carga.

## Arquitectura

`app.py` y `workers.py` siguen llamando `set_expression` / `set_brightness` / `set_pictogram`. El loop de ~30 fps no cambia de ritmo.

```
set_expression("feliz")
        ↓
EyeAnimator: si hay SpriteClip("feliz") → frame = f(tiempo, fps, loop)
        ↓
render(w, h) → PIL RGB (sprite escalado o elipses)
        ↓
LCD: lcd.display(frame)
tkinter: PhotoImage del mismo PIL si hay sprite; si no, ovals actuales
```

### Unidades

| Archivo | Responsabilidad |
|---|---|
| `eyes/` | Arte versionable. `.gitkeep` para la carpeta vacía. Los PNG/JSON de producción se commitean; no van al gitignore. |
| `eye_sprites.py` (nuevo) | `load_bank(directory) -> dict[str, SpriteClip]`. Default de `directory`: carpeta `eyes/` al lado de este archivo. Un stem inválido se omite (log), no tira el banco. |
| `eye_render.py` | `EyeAnimator(sprites_dir=None)` carga el banco al init. Con clip: elige frame, aplica brillo, pinta pictograma. Sin clip: `_draw` actual. Sin parpadeo procedural si hay clip. Al `set_expression` con clip, el reloj de frames vuelve a 0. Tests pasan un tempdir. |
| `eye_display.py` | LCD ya usa `render()`: sprites gratis. Tkinter: si la expresión actual tiene clip, blit del PIL; si no, `_draw_eyes`. |
| `test_eye_sprites.py` (nuevo) + `test_eye_render.py` | Tests sin LCD ni tkinter. |

`SpriteClip` (concepto, no API pública de app): lista de frames PIL 320×240, `fps`, `loop`, `frame_at(elapsed_s) -> Image`.

`frame_at`:

- `index = floor(elapsed * fps)`
- si `loop`: `index % frame_count`
- si no: `min(index, frame_count - 1)`

`render(width, height)`: si hay clip, toma el frame 320×240. Si el destino es 320×240, copia 1:1. Si no, escala con nearest-neighbor hasta **llenar** el rectángulo destino (HDMI y LCD se ven iguales de ocupados). No se recorta ni se letterboxea.

Brillo: igual que las elipses, multiplica RGB del frame por `brightness` (0..1).

Pictograma: texto encima del frame, misma posición/estilo que `_draw`.

Carga: una vez, en el `__init__` de `EyeAnimator`. Un archivo malo no aborta el resto. Loguear qué emociones cargaron. No hay reload: hay que reiniciar el proceso.

## Errores

Cualquiera de estos deja **esa** emoción en modo dibujado; la app no cae:

- Falta `.png` o `.json` (hace falta el par).
- JSON inválido o campos fuera de regla.
- PNG ilegible.
- Tamaño distinto de `columns*320` × `rows*240`.
- `frame_count` fuera de rango.
- Excepción al recortar.

Si tras validar no queda ningún frame, fallback procedural.

## Tests

PNG sintético en tempdir 640×240 (2 celdas de color sólido distinto al fondo y a la esclera) + JSON `{columns: 2, rows: 1, fps: 10, loop: true}`:

1. Recorta 2 frames 320×240.
2. `elapsed=0` → frame 0; `elapsed=0.15` → frame 1; loop vuelve a 0.
3. `loop: false` se queda en el último frame.
4. `render(320, 240)` con sprite no dibuja esclera procedural en la posición del ojo izquierdo de siempre.
5. Sin archivos / JSON roto / PNG 100×100 → `render()` igual que hoy (neutral elipses).
6. `zzz` y `pensando` sin PNG siguen texto y spinner.
7. `set_expression` a otra emoción con clip reinicia en frame 0.

No se exige test de SPI ni de tkinter PhotoImage en v1.

## Criterio de éxito

Con `eyes/feliz.png` + `feliz.json` válidos, `set_expression("feliz")` muestra la animación en LCD (y en tkinter si hay ventana). Sin esos archivos, el peluche se ve como antes de este cambio.
