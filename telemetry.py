"""telemetry.py — Recolección de métricas de uso para la app parental.

Registra interacciones clasificadas por pilar (emocional, cognitivo,
vincular, autonomía), eventos de crisis emocional y estadísticas de
sesión.  Todo se persiste en un JSON local sin PII (los textos ya
pasan por TextSanitizer antes de llegar aquí).

Diseñado para Edge Computing: JSON plano, sin base de datos.
"""
from __future__ import annotations

import json
from datetime import datetime, date
from pathlib import Path
from typing import Any


class TelemetryCollector:
    """Recolecta métricas de cada interacción y genera resúmenes diarios.

    Los datos se almacenan en un directorio local, con un archivo JSON
    por día: ``telemetry_YYYY-MM-DD.json``.
    """

    def __init__(self, data_dir: Path | None = None) -> None:
        if data_dir is None:
            data_dir = Path(__file__).resolve().parent / "telemetry_data"
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.session_start = datetime.now()
        self._today_file = self._get_today_file()
        self._today_data = self._load_or_create(self._today_file)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def log_interaction(
        self,
        pilar: str,
        intent_name: str,
        emotion: str | None = None,
        emotion_score: float = 0.0,
        duration_s: float = 0.0,
    ) -> None:
        """Registra una interacción clasificada por pilar."""
        self._ensure_today()
        event = {
            "type": "interaction",
            "timestamp": datetime.now().isoformat(),
            "pilar": pilar or "general",
            "intent": intent_name,
            "emotion": emotion,
            "emotion_score": round(emotion_score, 3),
            "duration_s": round(duration_s, 2),
        }
        self._today_data["events"].append(event)
        # Update pillar counters
        pillar_key = pilar or "general"
        self._today_data["summary"]["pillar_counts"][pillar_key] = (
            self._today_data["summary"]["pillar_counts"].get(pillar_key, 0) + 1
        )
        self._today_data["summary"]["total_interactions"] += 1
        self._today_data["summary"]["total_duration_s"] += duration_s
        self._save()

    def log_crisis_event(
        self,
        emotion: str,
        emotion_score: float,
        response: str,
    ) -> None:
        """Registra un evento de crisis emocional."""
        self._ensure_today()
        event = {
            "type": "crisis",
            "timestamp": datetime.now().isoformat(),
            "emotion": emotion,
            "emotion_score": round(emotion_score, 3),
            "response_given": response,
        }
        self._today_data["events"].append(event)
        self._today_data["summary"]["crisis_count"] = (
            self._today_data["summary"].get("crisis_count", 0) + 1
        )
        self._save()

    def log_game_session(
        self,
        game_type: str,
        rounds_played: int,
        duration_s: float = 0.0,
    ) -> None:
        """Registra una sesión de juego completada."""
        self._ensure_today()
        event = {
            "type": "game",
            "timestamp": datetime.now().isoformat(),
            "game_type": game_type,
            "rounds_played": rounds_played,
            "duration_s": round(duration_s, 2),
        }
        self._today_data["events"].append(event)
        self._today_data["summary"]["games_played"] = (
            self._today_data["summary"].get("games_played", 0) + 1
        )
        self._save()

    def log_routine_completed(self, routine_id: str, routine_name: str) -> None:
        """Registra la finalización exitosa de una rutina."""
        self._ensure_today()
        event = {
            "type": "routine_completed",
            "timestamp": datetime.now().isoformat(),
            "routine_id": routine_id,
            "routine_name": routine_name,
        }
        self._today_data["events"].append(event)
        self._today_data["summary"]["routines_completed"] = (
            self._today_data["summary"].get("routines_completed", 0) + 1
        )
        self._save()

    def log_vocabulary_update(self, new_words: list[str], total_words: int) -> None:
        """Registra un avance en vocabulario (sin PII)."""
        self._ensure_today()
        event = {
            "type": "vocabulary",
            "timestamp": datetime.now().isoformat(),
            "new_words_count": len(new_words),
            "total_known_words": total_words,
        }
        self._today_data["events"].append(event)
        self._today_data["summary"]["new_words_today"] = (
            self._today_data["summary"].get("new_words_today", 0) + len(new_words)
        )
        self._save()

    def get_daily_summary(self) -> dict[str, Any]:
        """Retorna el resumen del día actual."""
        self._ensure_today()
        return dict(self._today_data["summary"])

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_today_file(self) -> Path:
        return self.data_dir / f"telemetry_{date.today().isoformat()}.json"

    def _ensure_today(self) -> None:
        """Si cambió el día, rotar al archivo nuevo."""
        today_file = self._get_today_file()
        if today_file != self._today_file:
            self._save()  # guardar el día anterior
            self._today_file = today_file
            self._today_data = self._load_or_create(self._today_file)

    def _load_or_create(self, path: Path) -> dict[str, Any]:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {
            "date": date.today().isoformat(),
            "session_start": self.session_start.isoformat(),
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
        }

    def _save(self) -> None:
        try:
            self._today_file.write_text(
                json.dumps(self._today_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass
