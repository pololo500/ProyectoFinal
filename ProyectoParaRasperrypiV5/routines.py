"""routines.py — Sistema de rutinas y recordatorios programados.

Gestiona rutinas configuradas (ej. lavarse las manos, hora de comer)
y emite recordatorios via TTS en los horarios definidos.  Para el PoC,
las rutinas se cargan de un JSON local; en producción vendrán de la
app parental.

Incluye lógica de transición gradual entre actividades para reducir
la resistencia al cambio en el niño (#EPIC-007).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


class Routine:
    """Representación de una rutina individual."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.id: str = data.get("id", "unknown")
        self.name: str = data.get("name", "Rutina")
        self.time: str = data.get("time", "00:00")  # HH:MM
        self.reminder_message: str = data.get(
            "reminder_message",
            f"¡Es hora de {self.name.lower()}!",
        )
        self.transition_from: str = data.get("transition_from", "")
        self.transition_to: str = data.get("transition_to", "")
        self.success_message: str = data.get(
            "success_message",
            "¡Muy bien! ¡Lo lograste!",
        )
        self.pre_reminder_minutes: int = data.get("pre_reminder_minutes", 5)
        self.enabled: bool = data.get("enabled", True)
        # Estado de ejecución
        self._reminded_today: bool = False
        self._pre_reminded_today: bool = False
        self._completed_today: bool = False
        self._last_reminded_date: str = ""

    @property
    def time_hour(self) -> int:
        parts = self.time.split(":")
        return int(parts[0]) if parts else 0

    @property
    def time_minute(self) -> int:
        parts = self.time.split(":")
        return int(parts[1]) if len(parts) > 1 else 0

    def reset_daily(self) -> None:
        """Resetea el estado diario de la rutina."""
        today = datetime.now().strftime("%Y-%m-%d")
        if self._last_reminded_date != today:
            self._reminded_today = False
            self._pre_reminded_today = False
            self._completed_today = False
            self._last_reminded_date = today


class RoutineScheduler:
    """Gestiona rutinas y emite recordatorios según horario.

    Uso típico desde app.py::

        scheduler = RoutineScheduler(config_path)
        # En un timer periódico (cada 30s):
        messages = scheduler.check_pending()
        for msg in messages:
            speech_worker.speak(msg)
    """

    def __init__(self, config_path: Path | None = None) -> None:
        if config_path is None:
            config_path = Path(__file__).resolve().parent / "routines_config.json"
        self.config_path = config_path
        self.routines: list[Routine] = []
        self._load_config()

    def _load_config(self) -> None:
        """Carga rutinas desde el JSON de configuración."""
        if not self.config_path.exists():
            return
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            routines_data = data.get("routines", [])
            self.routines = [Routine(r) for r in routines_data]
        except Exception:
            self.routines = []

    def reload_config(self) -> None:
        """Recarga la configuración (para hot-reload desde la app)."""
        self._load_config()

    def check_pending(self) -> list[str]:
        """Verifica si hay rutinas pendientes de recordar.

        Retorna lista de mensajes TTS a emitir.
        Diseñado para ser llamado periódicamente (cada 30-60 segundos).
        """
        now = datetime.now()
        messages: list[str] = []

        for routine in self.routines:
            if not routine.enabled or routine._completed_today:
                continue
            routine.reset_daily()

            routine_time = now.replace(
                hour=routine.time_hour,
                minute=routine.time_minute,
                second=0,
                microsecond=0,
            )

            # Pre-recordatorio (transición gradual)
            pre_time = routine_time - timedelta(minutes=routine.pre_reminder_minutes)
            if not routine._pre_reminded_today and pre_time <= now < routine_time:
                routine._pre_reminded_today = True
                if routine.transition_from and routine.transition_to:
                    messages.append(
                        f"En un ratito vamos a pasar de {routine.transition_from} "
                        f"a {routine.transition_to}. "
                        f"¡Vamos terminando de a poquito!"
                    )

            # Recordatorio principal
            if not routine._reminded_today and now >= routine_time:
                # Solo recordar si no pasaron más de 30 minutos
                if (now - routine_time).total_seconds() < 1800:
                    routine._reminded_today = True
                    messages.append(routine.reminder_message)

        return messages

    def acknowledge_routine(self, routine_id: str) -> str | None:
        """Marca una rutina como completada y retorna mensaje de éxito.

        Se llama cuando el niño dice "ya terminé" o "listo".
        Si no hay rutina pendiente, intenta encontrar la más reciente.
        """
        # Buscar la rutina específica
        for routine in self.routines:
            if routine.id == routine_id and routine._reminded_today and not routine._completed_today:
                routine._completed_today = True
                return routine.success_message

        # Si no se especifica ID, completar la primera rutina pendiente
        if routine_id == "" or routine_id == "any":
            for routine in self.routines:
                if routine._reminded_today and not routine._completed_today:
                    routine._completed_today = True
                    return routine.success_message

        return None

    def get_pending_routine_id(self) -> str | None:
        """Retorna el ID de la primera rutina pendiente (reminded pero no completed)."""
        for routine in self.routines:
            if routine._reminded_today and not routine._completed_today:
                return routine.id
        return None

    def get_status(self) -> list[dict[str, Any]]:
        """Retorna estado de todas las rutinas para panel de debug."""
        return [
            {
                "id": r.id,
                "name": r.name,
                "time": r.time,
                "reminded": r._reminded_today,
                "completed": r._completed_today,
                "enabled": r.enabled,
            }
            for r in self.routines
        ]
