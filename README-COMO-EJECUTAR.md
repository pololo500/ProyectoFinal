# TEO

Peluche en Raspberry Pi (`ProyectoParaRasperrypiV5`) + app parental Android (`ProyectoAndroid`).

El entorno virtual de Python **no viene en el repo**. Hay que crearlo una vez y activarlo en cada sesión.

## Entorno Python (Pi / Windows)

Trabajá siempre dentro de `ProyectoParaRasperrypiV5`. Hace falta **Python 3.11**.

### Primera vez (clonar y armar el venv)

**Raspberry Pi** (instala apt, `uv`, venv y paquetes):

```bash
cd ProyectoParaRasperrypiV5
bash setup_pi.sh
```

`setup_pi.sh` **borra** un `venv` que ya exista. Usalo solo para instalar, no en cada arranque.

**Windows** (desarrollo):

```powershell
cd ProyectoParaRasperrypiV5
python3.11 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m spacy download es_core_news_md
```

Si `Activate.ps1` está bloqueado: `.\venv\Scripts\activate.bat`.

### Cada vez que abras una terminal

**Linux / Raspberry Pi:**

```bash
cd ProyectoParaRasperrypiV5
source venv/bin/activate
```

**Windows (PowerShell):**

```powershell
cd ProyectoParaRasperrypiV5
.\venv\Scripts\Activate.ps1
```

El prompt tiene que mostrar `(venv)`. Comprobá que el Python es el del entorno:

```bash
which python          # Linux / Pi → .../venv/bin/python
where python          # Windows → ...\venv\Scripts\python.exe
```

Correr el peluche:

```bash
python app.py
```

Tests:

```bash
python -m unittest test_session_policy test_intent_mute -v
```

### No hace falta

- Recrear el venv cada sesión.
- `sudo python app.py`.
- El Python del sistema (`/usr/bin/python3` o `py` global) para correr la app.

## App Android

No usa venv. Abrí `ProyectoAndroid` en Android Studio y dejá que Gradle baje las dependencias.
