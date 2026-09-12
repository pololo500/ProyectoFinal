"""api_server.py — Servidor REST embebido para comunicación con la App parental.

Provee una API HTTP liviana que corre en un hilo daemon, exponiendo
endpoints para que la app Android pueda consultar métricas, gestionar
rutinas, modificar configuración sensorial, enviar celebraciones y
controlar el estado del robot.

Usa exclusivamente la librería estándar de Python (http.server) para
no agregar dependencias externas, respetando los principios de Edge
Computing del proyecto.

Puerto por defecto: 8080.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import threading
import time
from datetime import date, datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from debug_logger import log_action
from pairing import load_or_create_token
from session_policy import sanitize_notification_extra, telemetry_range_summary

APP_DIR = Path(__file__).resolve().parent
MUSIC_DIR = APP_DIR / "music"
MUSIC_DIR.mkdir(exist_ok=True)
STORIES_DIR = APP_DIR / "stories"
STORIES_DIR.mkdir(exist_ok=True)


class RobotState:
    """Estado compartido entre el servidor API y la app principal."""

    def __init__(self) -> None:
        self.power_on: bool = True
        self.night_mode: bool = False
        self.volume_limit: int = 100       # 0-100
        self.brightness: float = 1.0       # 0.0-1.0
        self.playtime_limit_minutes: int = 0  # 0 = sin límite
        self.pairing_token: str = load_or_create_token()
        self.current_emotion: str | None = None
        self.current_emotion_score: float = 0.0
        self.currently_playing_song: str | None = None  # Canción en reproducción
        self.currently_reading: dict[str, str] | None = None
        self._lock = threading.Lock()

        # Cola de notificaciones para la app Android (crisis, logros, pedidos)
        self._notifications: list[dict[str, Any]] = []
        self._notifications_lock = threading.Lock()

        # Callbacks inyectados desde app.py
        self.on_celebrate: Callable[[], None] | None = None
        self.on_config_changed: Callable[[dict], None] | None = None
        self.on_night_mode_changed: Callable[[bool], None] | None = None
        self.on_power_changed: Callable[[bool], None] | None = None
        self.on_play_music: Callable[[str | None], bool] | None = None
        self.on_stop_music: Callable[[], None] | None = None
        self.on_play_story: Callable[[str], bool] | None = None
        self.on_stop_story: Callable[[], None] | None = None

        # Referencias a subsistemas (set from app.py)
        self.telemetry: Any = None
        self.routine_scheduler: Any = None
        self.speech_worker: Any = None

    def to_dict(self) -> dict[str, Any]:
        playing = None
        sw = self.speech_worker
        if sw is not None and getattr(sw, "_is_playing_music", False):
            playing = getattr(sw, "_current_song_name", None)
        with self._lock:
            return {
                "power_on": self.power_on,
                "night_mode": self.night_mode,
                "volume_limit": self.volume_limit,
                "brightness": self.brightness,
                "playtime_limit_minutes": self.playtime_limit_minutes,
                "current_emotion": self.current_emotion,
                "current_emotion_score": self.current_emotion_score,
                "currently_playing": playing,
                "currently_reading": dict(self.currently_reading) if self.currently_reading else None,
                "timestamp": datetime.now().isoformat(),
            }

    def update_config(self, data: dict) -> None:
        with self._lock:
            if "volume_limit" in data:
                self.volume_limit = max(0, min(100, int(data["volume_limit"])))
            if "brightness" in data:
                self.brightness = max(0.0, min(1.0, float(data["brightness"])))
            if "playtime_limit_minutes" in data:
                self.playtime_limit_minutes = max(0, min(240, int(data["playtime_limit_minutes"])))
        if self.on_config_changed:
            self.on_config_changed({
                "volume_limit": self.volume_limit,
                "brightness": self.brightness,
                "playtime_limit_minutes": self.playtime_limit_minutes,
            })

    def set_night_mode(self, enabled: bool) -> None:
        with self._lock:
            self.night_mode = enabled
        if self.on_night_mode_changed:
            self.on_night_mode_changed(enabled)

    def set_power(self, on: bool) -> None:
        with self._lock:
            self.power_on = on
        if self.on_power_changed:
            self.on_power_changed(on)

    def push_notification(
        self,
        notif_type: str,
        message: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Encola una notificación para la app Android.

        Args:
            notif_type: Tipo de notificación (crisis, logro, pedido, info).
            message: Descripción legible del evento.
            extra: Datos adicionales opcionales.
        """
        notif = {
            "type": notif_type,
            "message": message,
            "timestamp": datetime.now().isoformat(),
        }
        if extra:
            cleaned = sanitize_notification_extra(extra)
            if cleaned:
                notif["extra"] = cleaned
        with self._notifications_lock:
            # Máximo 50 notificaciones en cola (evitar memory leak)
            if len(self._notifications) >= 50:
                self._notifications.pop(0)
            self._notifications.append(notif)
        log_action("NOTIFY", f"{notif_type}: {message}")
        print(f"[API] Notificación encolada: [{notif_type}] {message}", flush=True)

    def pop_notifications(self) -> list[dict[str, Any]]:
        """Devuelve y vacía las notificaciones pendientes."""
        with self._notifications_lock:
            pending = list(self._notifications)
            self._notifications.clear()
        return pending


# Instancia global del estado del robot
robot_state = RobotState()


class ApiRequestHandler(BaseHTTPRequestHandler):
    """Maneja las peticiones HTTP de la app parental."""

    # Suprimir logs de acceso en consola (muy verbosos)
    def log_message(self, format: str, *args: Any) -> None:
        pass

    # ------------------------------------------------------------------
    # CORS headers (para desarrollo/testing desde navegador)
    # ------------------------------------------------------------------

    def _set_headers(self, status: int = 200, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Robot-Token, X-Filename, X-Story-Title")
        self.end_headers()

    def _send_json(self, data: Any, status: int = 200) -> None:
        self._set_headers(status)
        body = json.dumps(data, ensure_ascii=False, indent=2)
        self.wfile.write(body.encode("utf-8"))
        self._log_api_result(status)

    def _send_error_json(self, status: int, message: str) -> None:
        self._send_json({"error": message}, status)

    def _log_api_result(self, status: int) -> None:
        elapsed_ms = (time.monotonic() - getattr(self, "_req_t0", time.monotonic())) * 1000
        client = self.client_address[0] if self.client_address else "?"
        length = self.headers.get("Content-Length")
        size_bit = f" in={length}B" if length else ""
        log_action(
            "API",
            f"{self.command} {self.path} from {client} → {status}{size_bit}",
            elapsed_ms=elapsed_ms,
        )

    def setup(self) -> None:
        super().setup()
        self._req_t0 = time.monotonic()

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length)

    def _parse_json_body(self) -> dict | None:
        try:
            raw = self._read_body()
            if not raw:
                return {}
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    # ------------------------------------------------------------------
    # CORS preflight
    # ------------------------------------------------------------------

    def do_OPTIONS(self) -> None:
        self._set_headers(204)
        client = self.client_address[0] if self.client_address else "?"
        log_action("API", f"OPTIONS {self.path} from {client} → 204")

    # ------------------------------------------------------------------
    # GET endpoints
    # ------------------------------------------------------------------

    _PUBLIC_GET = {"/api/status", "/api/server-info"}

    def _authorized(self, path: str, mutating: bool) -> bool:
        if not mutating and path in self._PUBLIC_GET:
            return True
        token = robot_state.pairing_token
        if not token:
            return True
        provided = self.headers.get("X-Robot-Token", "")
        if provided and secrets.compare_digest(provided, token):
            return True
        self._send_error_json(401, "Token de vínculo inválido")
        return False

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        query = parse_qs(parsed.query)
        if not self._authorized(path, mutating=False):
            return

        if path == "/api/status":
            self._handle_get_status()
        elif path == "/api/server-info":
            self._handle_get_server_info()
        elif path == "/api/telemetry/range":
            self._handle_get_telemetry_range(query)
        elif path == "/api/telemetry/today":
            self._handle_get_telemetry(date.today().isoformat())
        elif path.startswith("/api/telemetry/"):
            date_str = path.split("/api/telemetry/")[1]
            self._handle_get_telemetry(date_str)
        elif path == "/api/routines":
            self._handle_get_routines()
        elif path == "/api/music":
            self._handle_get_music()
        elif path == "/api/stories":
            self._handle_get_stories()
        elif path.startswith("/api/stories/"):
            self._handle_get_story(path.split("/api/stories/", 1)[1])
        elif path == "/api/notifications":
            self._handle_get_notifications()
        else:
            self._send_error_json(404, "Endpoint no encontrado")

    def _handle_get_status(self) -> None:
        self._send_json(robot_state.to_dict())

    def _handle_get_server_info(self) -> None:
        """Devuelve información del servidor para debug de conexión."""
        import socket as _socket
        try:
            s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
            s.settimeout(0.5)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
        except Exception:
            local_ip = "0.0.0.0"
        self._send_json({
            "server_ip": local_ip,
            "server_port": 8080,
            "device_name": "MiCompañero Peluche",
            "connect_url": f"http://{local_ip}:8080",
            "pairing_token": robot_state.pairing_token,
        })

    def _handle_get_telemetry(self, date_str: str) -> None:
        telemetry = robot_state.telemetry
        if telemetry is None:
            self._send_json({
                "date": date_str,
                "summary": {
                    "total_interactions": 0,
                    "total_duration_s": 0.0,
                    "pillar_counts": {},
                    "crisis_count": 0,
                    "games_played": 0,
                    "routines_completed": 0,
                    "new_words_today": 0,
                },
                "events": [],
            })
            return

        # Intentar cargar el archivo de telemetría del día solicitado
        telemetry_file = telemetry.data_dir / f"telemetry_{date_str}.json"
        if telemetry_file.exists():
            try:
                data = json.loads(telemetry_file.read_text(encoding="utf-8"))
                self._send_json(data)
                return
            except Exception:
                pass

        # Si es hoy, usar los datos en memoria
        if date_str == date.today().isoformat():
            self._send_json({
                "date": date_str,
                "summary": telemetry.get_daily_summary(),
                "events": telemetry._today_data.get("events", []),
            })
        else:
            self._send_json({
                "date": date_str,
                "summary": {
                    "total_interactions": 0,
                    "total_duration_s": 0.0,
                    "pillar_counts": {},
                    "crisis_count": 0,
                    "games_played": 0,
                    "routines_completed": 0,
                    "new_words_today": 0,
                },
                "events": [],
            })

    def _handle_get_telemetry_range(self, query: dict[str, list[str]]) -> None:
        from datetime import timedelta

        try:
            days = int((query.get("days") or ["7"])[0])
        except (TypeError, ValueError):
            days = 7
        days = max(1, min(31, days))
        end = date.today()
        start = end - timedelta(days=days - 1)
        telemetry = robot_state.telemetry
        data_dir = telemetry.data_dir if telemetry is not None else APP_DIR / "telemetry_data"
        summary = telemetry_range_summary(data_dir, start, end)
        self._send_json({
            "from": start.isoformat(),
            "to": end.isoformat(),
            "summary": summary,
            "events": [],
        })

    def _handle_get_routines(self) -> None:
        scheduler = robot_state.routine_scheduler
        if scheduler is None:
            # Leer directamente del archivo de configuración
            config_path = APP_DIR / "routines_config.json"
            if config_path.exists():
                try:
                    data = json.loads(config_path.read_text(encoding="utf-8"))
                    self._send_json(data)
                    return
                except Exception:
                    pass
            self._send_json({"routines": []})
            return

        # Retornar configuración actual del scheduler + estado
        config_path = scheduler.config_path
        if config_path.exists():
            try:
                data = json.loads(config_path.read_text(encoding="utf-8"))
                # Agregar estado de ejecución
                status = scheduler.get_status()
                for i, routine_data in enumerate(data.get("routines", [])):
                    for s in status:
                        if s["id"] == routine_data.get("id"):
                            routine_data["reminded"] = s["reminded"]
                            routine_data["completed"] = s["completed"]
                            break
                self._send_json(data)
                return
            except Exception:
                pass
        self._send_json({"routines": []})

    def _handle_get_music(self) -> None:
        songs: list[dict[str, Any]] = []
        if MUSIC_DIR.exists():
            for f in sorted(MUSIC_DIR.iterdir()):
                if f.is_file() and f.suffix.lower() in (".mp3", ".wav", ".ogg", ".m4a", ".flac"):
                    songs.append({
                        "filename": f.name,
                        "size_bytes": f.stat().st_size,
                        "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                    })
        # Consultar canción en reproducción desde el speech_worker
        currently_playing: str | None = None
        sw = robot_state.speech_worker
        if sw is not None and hasattr(sw, '_is_playing_music') and sw._is_playing_music:
            currently_playing = getattr(sw, '_current_song_name', None)
        self._send_json({"songs": songs, "currently_playing": currently_playing})

    def _handle_get_stories(self) -> None:
        from story_library import StoryLibrary

        lib = StoryLibrary(STORIES_DIR)
        stories = [rec.to_dict() for rec in lib.list_stories()]
        self._send_json({"stories": stories})

    def _handle_get_story(self, story_id: str) -> None:
        import urllib.parse

        from story_library import StoryLibrary

        try:
            safe_id = urllib.parse.unquote(story_id)
        except Exception:
            safe_id = story_id
        lib = StoryLibrary(STORIES_DIR)
        rec = lib.get(safe_id)
        text = lib.load_text(safe_id)
        if rec is None or text is None:
            self._send_error_json(404, "Cuento no encontrado")
            return
        self._send_json({
            "id": rec.id,
            "title": rec.title,
            "word_count": rec.word_count,
            "created_at": rec.created_at,
            "text": text,
        })

    def _handle_get_notifications(self) -> None:
        """Devuelve y vacía las notificaciones pendientes.

        La app Android debería hacer polling a este endpoint cada 10-15s.
        Si hay notificaciones de tipo 'crisis', mostrar alerta inmediata.
        """
        pending = robot_state.pop_notifications()
        self._send_json({"notifications": pending, "count": len(pending)})

    # ------------------------------------------------------------------
    # POST endpoints
    # ------------------------------------------------------------------

    def do_POST(self) -> None:
        path = urlparse(self.path).path.rstrip("/")
        if not self._authorized(path, mutating=True):
            return

        if path == "/api/routines":
            self._handle_post_routines()
        elif path == "/api/config":
            self._handle_post_config()
        elif path == "/api/celebrate":
            self._handle_post_celebrate()
        elif path == "/api/night-mode":
            self._handle_post_night_mode()
        elif path == "/api/power":
            self._handle_post_power()
        elif path == "/api/music/upload":
            self._handle_post_music_upload()
        elif path == "/api/music/play":
            self._handle_post_music_play()
        elif path == "/api/music/stop":
            self._handle_post_music_stop()
        elif path == "/api/stories/upload":
            self._handle_post_stories_upload()
        elif path == "/api/stories/play":
            self._handle_post_stories_play()
        elif path == "/api/stories/stop":
            self._handle_post_stories_stop()
        else:
            self._send_error_json(404, "Endpoint no encontrado")

    def _handle_post_routines(self) -> None:
        body = self._parse_json_body()
        if body is None:
            self._send_error_json(400, "JSON inválido")
            return

        # Guardar en el archivo de configuración
        config_path = APP_DIR / "routines_config.json"
        try:
            config_path.write_text(
                json.dumps(body, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            self._send_error_json(500, f"Error al guardar: {exc}")
            return

        # Recargar en el scheduler si existe
        scheduler = robot_state.routine_scheduler
        if scheduler is not None:
            scheduler.reload_config()

        self._send_json({"status": "ok", "message": "Rutinas actualizadas"})

    def _handle_post_config(self) -> None:
        body = self._parse_json_body()
        if body is None:
            self._send_error_json(400, "JSON inválido")
            return

        robot_state.update_config(body)
        self._send_json({
            "status": "ok",
            "volume_limit": robot_state.volume_limit,
            "brightness": robot_state.brightness,
            "playtime_limit_minutes": robot_state.playtime_limit_minutes,
        })

    def _handle_post_celebrate(self) -> None:
        callback = robot_state.on_celebrate
        if callback:
            log_action("API", "celebrar logro")
            callback()
            self._send_json({"status": "ok", "message": "¡Celebración enviada!"})
        else:
            log_action("API", "celebrar logro RECHAZADO: callback no configurado")
            self._send_error_json(503, "Celebración no disponible")

    def _handle_post_night_mode(self) -> None:
        body = self._parse_json_body()
        if body is None:
            self._send_error_json(400, "JSON inválido")
            return

        enabled = bool(body.get("enabled", False))
        robot_state.set_night_mode(enabled)
        self._send_json({"status": "ok", "night_mode": enabled})

    def _handle_post_power(self) -> None:
        body = self._parse_json_body()
        if body is None:
            self._send_error_json(400, "JSON inválido")
            return

        power_on = bool(body.get("power_on", True))
        robot_state.set_power(power_on)
        self._send_json({"status": "ok", "power_on": power_on})

    def _handle_post_music_upload(self) -> None:
        """Recibe un archivo de música via streaming raw body con header X-Filename."""
        import urllib.parse

        raw_header = self.headers.get("X-Filename", "cancion.mp3")
        try:
            filename = urllib.parse.unquote(raw_header)
        except Exception:
            filename = raw_header

        # Sanear nombre de archivo
        safe_name = Path(filename).name
        if not safe_name:
            safe_name = "cancion.mp3"

        # Si no tiene extensión permitida, asegurar extensión .mp3
        allowed_ext = {".mp3", ".wav", ".ogg", ".m4a", ".flac"}
        if Path(safe_name).suffix.lower() not in allowed_ext:
            safe_name = f"{safe_name}.mp3"

        try:
            MUSIC_DIR.mkdir(parents=True, exist_ok=True)
            raw_data = self._read_body()
            if not raw_data:
                self._send_error_json(400, "Archivo recibido vacío")
                return

            dest = MUSIC_DIR / safe_name
            dest.write_bytes(raw_data)
            self._send_json({
                "status": "ok",
                "message": f"Canción '{safe_name}' subida correctamente",
                "filename": safe_name,
                "size_bytes": len(raw_data),
            })
        except Exception as exc:
            self._send_error_json(500, f"Error al guardar archivo: {exc}")

    def _handle_post_music_play(self) -> None:
        """Reproduce una canción específica o una al azar."""
        body = self._parse_json_body() or {}
        filename = body.get("filename")
        if robot_state.on_play_music:
            if robot_state.on_stop_story:
                robot_state.on_stop_story()
            robot_state.currently_playing_song = filename
            import threading
            threading.Thread(
                target=robot_state.on_play_music,
                args=(filename,),
                name="MusicPlayThread",
                daemon=True,
            ).start()
            self._send_json({"status": "ok", "message": f"Reproduciendo {filename or 'música'}"})
        else:
            self._send_error_json(503, "Reproductor de música no disponible")

    def _handle_post_music_stop(self) -> None:
        """Detiene la reproducción de música en curso."""
        if robot_state.on_stop_music:
            if robot_state.on_stop_story:
                robot_state.on_stop_story()
            robot_state.on_stop_music()
            robot_state.currently_playing_song = None
            self._send_json({"status": "ok", "message": "Música detenida"})
        else:
            self._send_error_json(503, "Reproductor de música no disponible")

    def _handle_post_stories_upload(self) -> None:
        import urllib.parse

        from story_library import ingest_pdf

        raw_header = self.headers.get("X-Filename", "cuento.pdf")
        try:
            filename = urllib.parse.unquote(raw_header)
        except Exception:
            filename = raw_header
        raw_title = self.headers.get("X-Story-Title")
        story_title = None
        if raw_title is not None:
            try:
                story_title = urllib.parse.unquote(raw_title)
            except Exception:
                story_title = raw_title
            story_title = story_title.strip() or None
        raw_data = self._read_body()
        result = ingest_pdf(raw_data, filename, stories_dir=STORIES_DIR, title=story_title)
        self._send_json(result)

    def _handle_post_stories_play(self) -> None:
        body = self._parse_json_body() or {}
        story_id = str(body.get("id") or "").strip()
        if not story_id:
            self._send_error_json(400, "Falta id del cuento")
            return
        if robot_state.on_play_story:
            ok = robot_state.on_play_story(story_id)
            if ok:
                self._send_json({"status": "ok", "id": story_id})
            else:
                self._send_error_json(404, "Cuento no encontrado")
        else:
            self._send_error_json(503, "Lector de cuentos no disponible")

    def _handle_post_stories_stop(self) -> None:
        if robot_state.on_stop_story:
            robot_state.on_stop_story()
            robot_state.currently_reading = None
            self._send_json({"status": "ok", "message": "Cuento detenido"})
        else:
            self._send_error_json(503, "Lector de cuentos no disponible")

    # ------------------------------------------------------------------
    # PUT endpoints
    # ------------------------------------------------------------------

    def do_PUT(self) -> None:
        path = urlparse(self.path).path.rstrip("/")
        if not self._authorized(path, mutating=True):
            return

        if path.startswith("/api/stories/"):
            story_id = path.split("/api/stories/", 1)[1]
            self._handle_put_story(story_id)
        else:
            self._send_error_json(404, "Endpoint no encontrado")

    def _handle_put_story(self, story_id: str) -> None:
        import urllib.parse

        from story_library import StoryLibrary

        body = self._parse_json_body()
        if body is None:
            self._send_error_json(400, "JSON inválido")
            return
        if "title" not in body and "text" not in body:
            self._send_error_json(400, "Falta título o texto")
            return

        title: str | None = None
        text: str | None = None
        if "title" in body:
            if not isinstance(body["title"], str):
                self._send_error_json(400, "JSON inválido")
                return
            title = body["title"].strip()
            if not title:
                self._send_error_json(400, "Título vacío")
                return
            title = title[:80]
        if "text" in body:
            if not isinstance(body["text"], str):
                self._send_error_json(400, "JSON inválido")
                return
            text = body["text"]

        try:
            safe_id = urllib.parse.unquote(story_id)
        except Exception:
            safe_id = story_id
        result = StoryLibrary(STORIES_DIR).update_story(safe_id, title=title, text=text)
        if result is None:
            self._send_error_json(404, "Cuento no encontrado")
            return
        self._send_json(result)

    # ------------------------------------------------------------------
    # DELETE endpoints
    # ------------------------------------------------------------------

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path.rstrip("/")
        if not self._authorized(path, mutating=True):
            return

        if path.startswith("/api/music/"):
            filename = path.split("/api/music/")[1]
            self._handle_delete_music(filename)
        elif path.startswith("/api/stories/"):
            story_id = path.split("/api/stories/")[1]
            self._handle_delete_story(story_id)
        else:
            self._send_error_json(404, "Endpoint no encontrado")

    def _handle_delete_music(self, filename: str) -> None:
        safe_name = Path(filename).name
        file_path = MUSIC_DIR / safe_name
        if not file_path.exists():
            self._send_error_json(404, f"Archivo '{safe_name}' no encontrado")
            return
        try:
            file_path.unlink()
            self._send_json({"status": "ok", "message": f"'{safe_name}' eliminado"})
        except Exception as exc:
            self._send_error_json(500, f"Error al eliminar: {exc}")

    def _handle_delete_story(self, story_id: str) -> None:
        import urllib.parse

        from story_library import StoryLibrary

        try:
            safe_id = urllib.parse.unquote(story_id)
        except Exception:
            safe_id = story_id
        lib = StoryLibrary(STORIES_DIR)
        if not lib.delete(safe_id):
            self._send_error_json(404, "Cuento no encontrado")
            return
        self._send_json({"status": "ok"})


class _DiscoveryBeacon:
    """Hilo daemon que envía broadcasts UDP periódicos para que la app
    Android pueda descubrir automáticamente la Raspberry Pi en la red local.

    Emite un paquete JSON en broadcast cada ``interval`` segundos
    en el puerto ``beacon_port``.
    """

    BEACON_PORT = 5555

    def __init__(self, api_port: int, interval: float = 1.5) -> None:
        self.api_port = api_port
        self.interval = interval
        self._running = False
        self._thread: threading.Thread | None = None

    def _get_local_ip(self) -> str:
        """Intenta obtener la IP local de la interfaz de red principal."""
        import socket as _socket
        try:
            s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
            s.settimeout(0.5)
            # No envía datos realmente; solo necesita un destino para
            # que el OS seleccione la interfaz de red correcta.
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "0.0.0.0"

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(
            target=self._broadcast_loop,
            daemon=True,
            name="DiscoveryBeacon",
        )
        self._thread.start()
        log_action("BEACON", f"inicio UDP :{self.BEACON_PORT} cada {self.interval}s")

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        log_action("BEACON", "detenido")

    def _broadcast_loop(self) -> None:
        import socket as _socket
        sock = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
        sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_BROADCAST, 1)
        sock.settimeout(1.0)

        local_ip = self._get_local_ip()
        beacon_data = json.dumps({
            "device_id": "micompanero_robot",
            "device_name": "MiCompañero Peluche",
            "api_port": self.api_port,
            "local_ip": local_ip,
            "pairing_token": robot_state.pairing_token,
        }, ensure_ascii=False).encode("utf-8")

        print(
            f"[API] Beacon de descubrimiento activo en UDP :{self.BEACON_PORT} "
            f"(intervalo: {self.interval}s, IP local: {local_ip})",
            flush=True,
        )

        _reminder_counter = 0
        _reminder_interval = int(60 / self.interval)  # cada ~60 segundos

        while self._running:
            try:
                sock.sendto(beacon_data, ("<broadcast>", self.BEACON_PORT))
            except Exception:
                pass

            # Recordatorio periódico de IP en consola (cada ~60 segundos)
            _reminder_counter += 1
            if _reminder_counter >= _reminder_interval:
                _reminder_counter = 0
                # Re-obtener la IP por si cambió (ej: reconexión WiFi)
                current_ip = self._get_local_ip()
                if current_ip != local_ip:
                    local_ip = current_ip
                    beacon_data = json.dumps({
                        "device_id": "micompanero_robot",
                        "device_name": "MiCompañero Peluche",
                        "api_port": self.api_port,
                        "local_ip": local_ip,
                        "pairing_token": robot_state.pairing_token,
                    }, ensure_ascii=False).encode("utf-8")
                print(
                    f"\n┌─────────────────────────────────────────┐\n"
                    f"│  🌐 IP del robot:  {local_ip:<22s}│\n"
                    f"│  Puerto API:       {self.api_port:<22d}│\n"
                    f"└─────────────────────────────────────────┘",
                    flush=True,
                )

            time.sleep(self.interval)

        sock.close()


class ApiServer:
    """Servidor HTTP + beacon de descubrimiento que corre en hilos daemon."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8080) -> None:
        self.host = host
        self.port = port
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._beacon: _DiscoveryBeacon | None = None

    def start(self) -> None:
        """Inicia el servidor HTTP y el beacon de descubrimiento."""
        # HTTP server
        self._server = HTTPServer((self.host, self.port), ApiRequestHandler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
            name="ApiServer",
        )
        self._thread.start()

        # Obtain local IP for display
        import socket as _socket
        try:
            s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
            s.settimeout(0.5)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
        except Exception:
            local_ip = "0.0.0.0"

        print(flush=True)
        print("╔══════════════════════════════════════════════════╗", flush=True)
        print("║        🧸 SERVIDOR API - MiCompañero            ║", flush=True)
        print("╠══════════════════════════════════════════════════╣", flush=True)
        print(f"║  IP local:  {local_ip:<37s}║", flush=True)
        print(f"║  Puerto:    {self.port:<37d}║", flush=True)
        print("╠══════════════════════════════════════════════════╣", flush=True)
        print(f"║  👉 En la app Android, ingresá: {local_ip:<17s}║", flush=True)
        print("║  👉 En emulador Android, usá:   10.0.2.2        ║", flush=True)
        print("╠══════════════════════════════════════════════════╣", flush=True)
        print("║  ℹ️  La IP se repetirá en consola cada 60 seg   ║", flush=True)
        print(f"║  Token vínculo: {robot_state.pairing_token[:12]}… (pairing_token.txt) ║", flush=True)
        print("╚══════════════════════════════════════════════════╝", flush=True)
        print(flush=True)

        # UDP discovery beacon
        self._beacon = _DiscoveryBeacon(api_port=self.port)
        self._beacon.start()
        log_action("API", f"servidor REST escuchando en {self.host}:{self.port} (IP {local_ip})")

    def stop(self) -> None:
        """Detiene el servidor y el beacon."""
        if self._beacon:
            self._beacon.stop()
            self._beacon = None
        if self._server:
            self._server.shutdown()
            self._server = None
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None
        print("[API] Servidor REST detenido", flush=True)
        log_action("API", "servidor REST detenido")


# ------------------------------------------------------------------
# Standalone mode for quick testing
# ------------------------------------------------------------------

if __name__ == "__main__":
    import signal
    import sys

    print("=" * 60)
    print("  API Server — Modo de prueba standalone")
    print("=" * 60)
    print()

    server = ApiServer()
    server.start()

    print()
    print("Servidor corriendo. Endpoints disponibles:")
    print(f"  GET  http://localhost:8080/api/status")
    print(f"  GET  http://localhost:8080/api/telemetry/today")
    print(f"  GET  http://localhost:8080/api/routines")
    print(f"  GET  http://localhost:8080/api/music")
    print(f"  POST http://localhost:8080/api/stories/play")
    print(f"  POST http://localhost:8080/api/stories/stop")
    print(f"  POST http://localhost:8080/api/celebrate")
    print(f"  POST http://localhost:8080/api/config")
    print(f"  POST http://localhost:8080/api/night-mode")
    print(f"  POST http://localhost:8080/api/power")
    print()
    print("Desde el emulador de Android Studio, usá: 10.0.2.2:8080")
    print("Presioná Ctrl+C para detener.")
    print()

    def _signal_handler(sig, frame):
        print("\nDeteniendo servidor...")
        server.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _signal_handler)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.stop()
