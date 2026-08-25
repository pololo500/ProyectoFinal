# Cuentos PDF — plan de implementación

> Ejecutar en esta sesión. Tests de dominio en `ProyectoParaRasperrypiV5/test_stories.py` (mismo estilo que `test_full.py`).

**Goal:** El adulto sube un PDF; la Pi extrae y valida texto; TEO lista y lee el cuento sin que el LLM lo invente.

**Architecture:** `story_validate` + `story_library` + `story_engine` en la Pi; API como música; pestaña Android `nav_stories`.

**Tech:** Python 3.11, pypdf, Piper existente, HttpURLConnection Android.

## Global Constraints

- Validación local, sin Groq. Solo persistir `ready`. PDF ≤ 8 MB y ≤ 15 páginas.
- TTS de cuento: no truncar a 25 palabras. Leer por párrafos.
- Pestaña aparte (cajón + overflow), no en Configuración ni en bottom nav.
- Opción C (preguntas entre párrafos) no se implementa.

## Archivos

Crear:
- `ProyectoParaRasperrypiV5/story_validate.py`
- `ProyectoParaRasperrypiV5/story_library.py`
- `ProyectoParaRasperrypiV5/story_engine.py`
- `ProyectoParaRasperrypiV5/test_stories.py`
- `ProyectoParaRasperrypiV5/stories/.gitkeep`
- Android: `StoriesFragment`, `StoriesViewModel`, `fragment_stories.xml`, `ic_stories_24dp.xml`

Modificar:
- `requirements.txt` (pypdf)
- `api_server.py` GET/POST/DELETE `/api/stories`
- `workers.py` keyword + engine + TTS chunks
- `intent_rules.json` `story_request`
- `cloud_services.py` / `fallback_llm.py` prompts
- Android: `RobotApiClient`, `RobotConnectionManager`, nav, menus, `MainActivity`, strings

## Tasks

1. Validación + biblioteca + engine (TDD `test_stories.py`)
2. API + workers + intents + prompts
3. App Android pestaña Cuentos
4. Correr `python test_stories.py`

No commitear salvo que Teo lo pida.
