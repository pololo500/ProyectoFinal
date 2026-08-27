"""Yoga infantil guiado: tres posturas, el nene dice “listo” para avanzar."""
from __future__ import annotations

import re
from typing import Any

from debug_logger import log_action

_POSES = [
    "Poné los pies juntos y levantá los brazos como un árbol grande. Cuando termines, decime listo.",
    "Ahora hacé el gato: apoyá rodillas y manitos, y arqueá la espalda despacito. ¿Listo?",
    "Última: tirate al piso y abrí brazos y piernas como una estrella. Decime ya cuando acabes.",
]

_ADVANCE = re.compile(r"\b(listo|ya|dale|ok|okay|segui|seguí|termine|terminé)\b", re.IGNORECASE)
_EXIT = re.compile(r"\b(basta|parar|chau|no quiero)\b", re.IGNORECASE)


class YogaEngine:
    def __init__(self) -> None:
        self._index: int = -1

    @property
    def is_active(self) -> bool:
        return self._index >= 0

    def start(self) -> str:
        self._index = 0
        log_action("YOGA", "inicio")
        return f"¡Vamos a hacer yoga! {_POSES[0]}"

    def process_or_passthrough(
        self,
        text: str,
        dispatcher_result: dict[str, Any],
    ) -> dict[str, Any]:
        intent_name = dispatcher_result.get("intent_name", "")
        if not self.is_active:
            if intent_name == "yoga_request":
                return self._payload(self.start())
            return dispatcher_result

        if _EXIT.search(text or ""):
            self._index = -1
            log_action("YOGA", "corte")
            return self._payload("Listo, descansamos. Lo hiciste bárbaro.")

        if _ADVANCE.search(text or "") or intent_name == "yoga_request":
            self._index += 1
            if self._index >= len(_POSES):
                self._index = -1
                log_action("YOGA", "completo")
                return self._payload("¡Muy bien! Estiramos el cuerpo. ¿Querés un abrazo?")
            return self._payload(_POSES[self._index])

        return self._payload("Cuando termines esa postura, decime listo.")

    @staticmethod
    def _payload(response: str) -> dict[str, Any]:
        return {
            "intent_name": "yoga_pose",
            "confidence": 1.0,
            "response": response,
            "pilar": "emocional",
        }
