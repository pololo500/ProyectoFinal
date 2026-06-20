"""game_engine.py — Motor de juegos interactivos multi-turno.

Implementa juegos conversacionales (Veo-veo, Piedra-papel-tijera) con
máquina de estados que mantiene contexto entre turnos.  Cuando hay un
juego activo, el input del niño se redirige aquí en vez del dispatcher
de intenciones normal.

Diseñado para Edge Computing: sin dependencias extra, lógica pura Python.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Respuestas y datos de juego
# ---------------------------------------------------------------------------

_VEO_VEO_COLORS = [
    "rojo", "azul", "verde", "amarillo", "naranja",
    "rosa", "blanco", "negro", "marrón", "violeta",
]

_VEO_VEO_OBJECTS: dict[str, list[str]] = {
    "rojo": ["manzana", "corazón", "tomate", "frutilla"],
    "azul": ["cielo", "mar", "agua", "globo azul"],
    "verde": ["pasto", "árbol", "hoja", "rana"],
    "amarillo": ["sol", "banana", "pollito", "estrella"],
    "naranja": ["naranja", "zanahoria", "calabaza"],
    "rosa": ["flor", "flamenco", "algodón de azúcar"],
    "blanco": ["nube", "nieve", "leche", "algodón"],
    "negro": ["noche", "gato negro", "hormiga"],
    "marrón": ["chocolate", "oso", "tronco", "tierra"],
    "violeta": ["uva", "berenjena", "flor violeta"],
}

_PIEDRA_PAPEL_CHOICES = ["piedra", "papel", "tijera"]

_CELEBRATION_PHRASES = [
    "¡Muy bien! ¡Sos un genio!",
    "¡Excelente! ¡Lo adivinaste!",
    "¡Bravo! ¡Qué crack que sos!",
    "¡Increíble! ¡Sabía que podías!",
]

_ENCOURAGEMENT_PHRASES = [
    "¡Casi casi! Intentá de nuevo, vos podés.",
    "¡Buen intento! Dale, otra vez.",
    "Mmm no era esa, pero estás muy cerca. ¡Probá otra vez!",
]

_WIN_PHRASES = [
    "¡Ganaste vos! ¡Felicitaciones, campeón!",
    "¡Me ganaste! Sos muy bueno en esto.",
]

_LOSE_PHRASES = [
    "¡Gané yo esta vez! Pero jugaste muy bien. ¿Otra ronda?",
    "¡Esta vez gané! ¿Revancha?",
]

_TIE_PHRASES = [
    "¡Empatamos! Pensamos igual. ¿Otra vez?",
    "¡Empate! ¡Qué coincidencia! Dale de nuevo.",
]


# ---------------------------------------------------------------------------
# Datos de respuesta de juego
# ---------------------------------------------------------------------------

@dataclass
class GameResponse:
    """Resultado de procesar un turno de juego."""
    text: str               # Texto para TTS
    game_over: bool = False # True si el juego terminó
    pilar: str = "cognitivo"


# ---------------------------------------------------------------------------
# Sesiones de juego
# ---------------------------------------------------------------------------

@dataclass
class VeoVeoSession:
    """Juego Veo-veo con múltiples rondas.

    Flujo:
    1. Robot elige color secreto + objeto.
    2. Robot dice: "Veo veo una cosita de color {color}. ¿Qué será?"
    3. Niño responde.
    4. Si acierta → celebración + nueva ronda o fin.
    5. Si falla → ánimo + pista + retry (máx 3 intentos por ronda).
    """
    color: str = ""
    secret_object: str = ""
    attempts: int = 0
    max_attempts: int = 3
    rounds_played: int = 0
    max_rounds: int = 3
    state: str = "waiting_answer"  # waiting_answer

    def start_round(self) -> str:
        """Inicia una nueva ronda eligiendo color y objeto."""
        self.color = random.choice(_VEO_VEO_COLORS)
        objects = _VEO_VEO_OBJECTS.get(self.color, ["algo misterioso"])
        self.secret_object = random.choice(objects)
        self.attempts = 0
        self.state = "waiting_answer"
        return (
            f"Veo veo... una cosita de color {self.color}. "
            f"¿Qué será, qué será?"
        )

    def process_input(self, text: str) -> GameResponse:
        """Procesa la respuesta del niño."""
        normalized = text.lower().strip()

        # Detectar si quiere salir del juego
        exit_words = {"no quiero", "basta", "salir", "parar", "chau", "no"}
        if any(word in normalized for word in exit_words):
            return GameResponse(
                text="¡Fue muy divertido jugar al Veo-veo con vos! "
                     "Cuando quieras jugamos de nuevo.",
                game_over=True,
            )

        self.attempts += 1

        # Verificar si acertó (coincidencia parcial)
        if self.secret_object.lower() in normalized or normalized in self.secret_object.lower():
            self.rounds_played += 1
            celebration = random.choice(_CELEBRATION_PHRASES)

            if self.rounds_played >= self.max_rounds:
                return GameResponse(
                    text=f"{celebration} ¡Era {self.secret_object}! "
                         f"Jugamos {self.max_rounds} rondas. ¡Sos increíble!",
                    game_over=True,
                )
            else:
                next_round = self.start_round()
                return GameResponse(
                    text=f"{celebration} ¡Era {self.secret_object}! "
                         f"¡Vamos con otra! {next_round}",
                )
        else:
            if self.attempts >= self.max_attempts:
                self.rounds_played += 1
                if self.rounds_played >= self.max_rounds:
                    return GameResponse(
                        text=f"¡Era {self.secret_object}! No te preocupes, "
                             f"estuvo muy bien. Jugamos {self.max_rounds} rondas. "
                             f"¡La próxima las adivinás todas!",
                        game_over=True,
                    )
                else:
                    next_round = self.start_round()
                    return GameResponse(
                        text=f"¡Era {self.secret_object}! No pasa nada, "
                             f"¡vamos con otra! {next_round}",
                    )
            else:
                encouragement = random.choice(_ENCOURAGEMENT_PHRASES)
                hint = f"Te doy una pista: empieza con la letra {self.secret_object[0].upper()}."
                return GameResponse(
                    text=f"{encouragement} {hint}",
                )


@dataclass
class PiedraPapelTijeraSession:
    """Juego Piedra-papel-tijera.

    Flujo:
    1. Robot dice: "¡Uno, dos, tres!"
    2. Niño elige: piedra, papel o tijera.
    3. Robot elige al azar, resuelve y anuncia resultado.
    4. Se juegan múltiples rondas.
    """
    rounds_played: int = 0
    max_rounds: int = 3
    wins_child: int = 0
    wins_robot: int = 0
    state: str = "waiting_choice"

    def process_input(self, text: str) -> GameResponse:
        """Procesa la elección del niño."""
        normalized = text.lower().strip()

        # Detectar si quiere salir
        exit_words = {"no quiero", "basta", "salir", "parar", "chau"}
        if any(word in normalized for word in exit_words):
            return self._end_game()

        # Detectar elección del niño
        child_choice = None
        for choice in _PIEDRA_PAPEL_CHOICES:
            if choice in normalized:
                child_choice = choice
                break

        if child_choice is None:
            return GameResponse(
                text="No entendí tu elección. Decí piedra, papel o tijera. "
                     "¡Uno, dos, tres!",
            )

        robot_choice = random.choice(_PIEDRA_PAPEL_CHOICES)
        self.rounds_played += 1

        result = self._resolve(child_choice, robot_choice)

        if result == "tie":
            phrase = random.choice(_TIE_PHRASES)
        elif result == "child_wins":
            self.wins_child += 1
            phrase = random.choice(_WIN_PHRASES)
        else:
            self.wins_robot += 1
            phrase = random.choice(_LOSE_PHRASES)

        response_text = (
            f"Yo elegí {robot_choice}. {phrase}"
        )

        if self.rounds_played >= self.max_rounds:
            return self._end_game(prefix=response_text)

        response_text += " ¡Uno, dos, tres!"
        return GameResponse(text=response_text)

    def _resolve(self, child: str, robot: str) -> str:
        """Resuelve quién gana."""
        if child == robot:
            return "tie"
        wins = {
            ("piedra", "tijera"),
            ("papel", "piedra"),
            ("tijera", "papel"),
        }
        return "child_wins" if (child, robot) in wins else "robot_wins"

    def _end_game(self, prefix: str = "") -> GameResponse:
        """Finaliza el juego con resumen."""
        summary = (
            f"Jugamos {self.rounds_played} rondas. "
            f"Vos ganaste {self.wins_child} y yo gané {self.wins_robot}. "
        )
        if self.wins_child > self.wins_robot:
            summary += "¡Ganaste vos! ¡Felicitaciones, campeón!"
        elif self.wins_robot > self.wins_child:
            summary += "¡Gané yo esta vez! Pero jugaste increíble."
        else:
            summary += "¡Empatamos! Somos un gran equipo."

        full_text = f"{prefix} {summary}".strip() if prefix else summary
        return GameResponse(text=full_text, game_over=True)


# ---------------------------------------------------------------------------
# Motor principal de juegos
# ---------------------------------------------------------------------------

class GameEngine:
    """Gestiona la sesión de juego activa.

    Si hay un juego en curso, el input del niño se procesa aquí.
    Si no, el flujo normal del IntentDispatcher toma el control.
    """

    def __init__(self) -> None:
        self._session: VeoVeoSession | PiedraPapelTijeraSession | None = None

    @property
    def is_active(self) -> bool:
        return self._session is not None

    @property
    def game_type(self) -> str | None:
        if isinstance(self._session, VeoVeoSession):
            return "veo_veo"
        if isinstance(self._session, PiedraPapelTijeraSession):
            return "piedra_papel_tijera"
        return None

    def start_game(self, game_type: str) -> str:
        """Inicia un juego nuevo y retorna el mensaje de bienvenida."""
        if game_type == "veo_veo":
            session = VeoVeoSession()
            opening = session.start_round()
            self._session = session
            return f"¡Dale, juguemos al Veo-veo! {opening}"
        elif game_type == "piedra_papel_tijera":
            self._session = PiedraPapelTijeraSession()
            return (
                "¡Dale, juguemos a Piedra, papel o tijera! "
                "¿Listo? ¡Uno, dos, tres!"
            )
        else:
            return ""

    def process_input(self, text: str) -> GameResponse | None:
        """Procesa input cuando hay juego activo.

        Retorna None si no hay juego activo (passthrough al dispatcher).
        """
        if self._session is None:
            return None

        response = self._session.process_input(text)
        if response.game_over:
            self._session = None
        return response

    def process_or_passthrough(
        self,
        text: str,
        dispatcher_result: dict[str, Any],
    ) -> dict[str, Any]:
        """Si hay juego activo, procesa y retorna resultado de juego.
        Si no, retorna el dispatcher_result sin modificar.

        Retorna un dict compatible con el formato de intent_payload:
        {"intent_name": str, "confidence": float, "response": str, "pilar": str}
        """
        if not self.is_active:
            # Verificar si el dispatcher detectó un intent de juego
            intent_name = dispatcher_result.get("intent_name", "")
            game_type = None
            if intent_name == "play_veo_veo":
                game_type = "veo_veo"
            elif intent_name == "play_piedra_papel":
                game_type = "piedra_papel_tijera"

            if game_type:
                welcome = self.start_game(game_type)
                return {
                    "intent_name": intent_name,
                    "confidence": dispatcher_result.get("confidence", 1.0),
                    "response": welcome,
                    "pilar": "cognitivo",
                    "game_started": True,
                }
            return dispatcher_result

        # Juego activo: procesar input
        game_response = self.process_input(text)
        if game_response is None:
            return dispatcher_result

        return {
            "intent_name": f"game_{self.game_type or 'unknown'}",
            "confidence": 1.0,
            "response": game_response.text,
            "pilar": game_response.pilar,
            "game_over": game_response.game_over,
        }

    def cancel(self) -> None:
        """Cancela cualquier juego en curso."""
        self._session = None
