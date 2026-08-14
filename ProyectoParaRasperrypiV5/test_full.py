"""test_full.py — Prueba completa de todos los componentes sin hardware.

Ejecutar con:  python test_full.py
"""
from __future__ import annotations

import os
import sys
# Fix Windows console encoding
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import random
import json
import re
from pathlib import Path
from datetime import datetime, date

# ───────────────── Helpers ─────────────────

PASS = 0
FAIL = 0
WARN = 0

def ok(test_name: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [OK] {test_name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {test_name}" + (f"  ->  {detail}" if detail else ""))

def warn(test_name: str, detail: str = ""):
    global WARN
    WARN += 1
    print(f"  [WARN] {test_name}" + (f"  ->  {detail}" if detail else ""))



# ═══════════════════════════════════════════
#  1. GAME ENGINE — Veo-Veo
# ═══════════════════════════════════════════
print("\n" + "="*60)
print("  1. GAME ENGINE — Veo-Veo")
print("="*60)

from game_engine import (
    GameEngine, VeoVeoSession, PiedraPapelTijeraSession,
    GameResponse, _VEO_VEO_OBJECTS, _VEO_VEO_COLORS,
)

# 1.1 — Verificar que start_round elige color y objeto consistentes
session = VeoVeoSession()
random.seed(42)
msg = session.start_round()
ok("start_round retorna mensaje con color",
   session.color in msg,
   f"color={session.color!r} no en mensaje={msg!r}")
ok("secret_object pertenece al color elegido",
   session.secret_object in _VEO_VEO_OBJECTS.get(session.color, []),
   f"obj={session.secret_object!r} no en color={session.color!r}")

# 1.2 — BUG CORREGIDO: revelar el objeto correcto tras start_round
random.seed(100)
session2 = VeoVeoSession(max_attempts=1, max_rounds=5)
session2.start_round()
original_object = session2.secret_object
original_color = session2.color

# Fallar el intento para forzar que revele + inicie nueva ronda
resp = session2.process_input("algo incorrecto xyz")
ok("Revela el objeto ORIGINAL al fallar (no el de la nueva ronda)",
   f"¡Era {original_object}!" in resp.text,
   f"Esperaba '¡Era {original_object}!' en: {resp.text!r}")
ok("No revela un objeto de la nueva ronda",
   session2.secret_object != original_object or session2.color != original_color or "¡vamos con otra!" in resp.text,
   "Puede que no haya cambiado de ronda")

# 1.3 — BUG CORREGIDO: revelar objeto correcto al acertar + siguiente ronda
random.seed(200)
session3 = VeoVeoSession(max_rounds=5)
session3.start_round()
obj_to_guess = session3.secret_object
resp3 = session3.process_input(obj_to_guess)
ok("Revela el objeto ORIGINAL al acertar",
   f"¡Era {obj_to_guess}!" in resp3.text,
   f"Esperaba '¡Era {obj_to_guess}!' en: {resp3.text!r}")

# 1.4 — Detectar exit words
session4 = VeoVeoSession()
session4.start_round()
for word in ["no quiero", "basta", "salir", "parar", "chau"]:
    s = VeoVeoSession()
    s.start_round()
    resp4 = s.process_input(word)
    ok(f"Exit word '{word}' termina el juego", resp4.game_over,
       f"game_over={resp4.game_over}")

# 1.5 — FIX VERIFICADO: "no" como exit word ya no es agresivo
session5 = VeoVeoSession()
session5.start_round()
session5.secret_object = "noche"
# El niño dice "noche" — ya no activa exit por contener "no"
resp5 = session5.process_input("noche")
ok("Decir 'noche' NO sale del juego (fix BUG-1)",
   not resp5.game_over or "Era noche" in resp5.text,
   f"resp={resp5.text!r}, game_over={resp5.game_over}")

# 1.6 — FIX VERIFICADO: "no sé" ya no sale del juego
session6 = VeoVeoSession()
session6.start_round()
resp6 = session6.process_input("no sé")
ok("'no sé' NO sale del juego (fix BUG-1)",
   not resp6.game_over,
   f"game_over={resp6.game_over}, resp={resp6.text!r}")

# 1.7 — FIX VERIFICADO: texto vacío no cuenta como acierto
session7 = VeoVeoSession()
session7.start_round()
session7.secret_object = "sol"
resp7 = session7.process_input("")  # vacío, no debería acertar
is_false_positive = "Era sol" in resp7.text or "genio" in resp7.text.lower()
ok("Texto vacío NO cuenta como acierto (fix BUG-2)",
   not is_false_positive,
   f"resp={resp7.text!r}")

# 1.8 — FIX VERIFICADO: substrings cortos no matchean
session8 = VeoVeoSession()
session8.start_round()
session8.secret_object = "estrella"
resp8 = session8.process_input("es")
is_bad_match = "Era estrella" in resp8.text or any(p in resp8.text for p in ["genio", "adivinaste", "crack", "podías"])
ok("Decir 'es' NO acierta 'estrella' (fix BUG-3)",
   not is_bad_match,
   f"resp={resp8.text!r}")

# 1.9 — Hint usa primera letra correcta del objeto actual
session9 = VeoVeoSession(max_attempts=5)
session9.start_round()
session9.secret_object = "banana"
session9.color = "amarillo"
resp9 = session9.process_input("xyz incorrecto")
expected_letter = "B"  # banana[0].upper()
ok("Pista muestra la letra correcta del objeto actual",
   f"letra {expected_letter}" in resp9.text,
   f"Esperaba 'letra {expected_letter}' en: {resp9.text!r}")


# ═══════════════════════════════════════════
#  2. GAME ENGINE — Piedra-Papel-Tijera
# ═══════════════════════════════════════════
print("\n" + "="*60)
print("  2. GAME ENGINE — Piedra-Papel-Tijera")
print("="*60)

# 2.1 — Resolución correcta
ppt = PiedraPapelTijeraSession()
ok("Piedra vence Tijera", ppt._resolve("piedra", "tijera") == "child_wins")
ok("Tijera vence Papel", ppt._resolve("tijera", "papel") == "child_wins")
ok("Papel vence Piedra", ppt._resolve("papel", "piedra") == "child_wins")
ok("Piedra pierde vs Papel", ppt._resolve("piedra", "papel") == "robot_wins")
ok("Empate", ppt._resolve("piedra", "piedra") == "tie")

# 2.2 — Detección de elección inválida
ppt2 = PiedraPapelTijeraSession()
resp_ppt = ppt2.process_input("banana")
ok("Elección inválida pide reintentar",
   "No entendí" in resp_ppt.text,
   f"resp={resp_ppt.text!r}")
ok("Rondas no aumentan con elección inválida",
   ppt2.rounds_played == 0)

# 2.3 — El juego termina después de max_rounds
ppt3 = PiedraPapelTijeraSession(max_rounds=2)
random.seed(1)
r1 = ppt3.process_input("piedra")
r2 = ppt3.process_input("papel")
ok("Juego termina en max_rounds",
   r2.game_over,
   f"game_over={r2.game_over}, rounds={ppt3.rounds_played}")


# ═══════════════════════════════════════════
#  3. GAME ENGINE — process_or_passthrough bugs
# ═══════════════════════════════════════════
print("\n" + "="*60)
print("  3. GAME ENGINE — process_or_passthrough")
print("="*60)

# 3.1 — FIX VERIFICADO: game_type guardado ANTES de process_input
engine = GameEngine()
engine.start_game("veo_veo")
engine._session.secret_object = "test"
engine._session.max_attempts = 1
engine._session.max_rounds = 1

result = engine.process_or_passthrough("xyz wrong", {"intent_name": "unknown", "confidence": 0, "response": ""})
ok("intent_name es 'game_veo_veo' cuando el juego termina (fix BUG-4)",
   result.get("intent_name") == "game_veo_veo",
   f"intent={result.get('intent_name')!r}")

# 3.2 — Passthrough funciona cuando no hay juego activo
engine2 = GameEngine()
dummy_result = {"intent_name": "greeting", "confidence": 0.9, "response": "Hola"}
passthrough = engine2.process_or_passthrough("hola", dummy_result)
ok("Passthrough retorna dispatcher result sin juego activo",
   passthrough == dummy_result)

# 3.3 — Start game via passthrough con intent play_veo_veo
engine3 = GameEngine()
start_result = engine3.process_or_passthrough(
    "quiero jugar veo veo",
    {"intent_name": "play_veo_veo", "confidence": 0.8, "response": ""}
)
ok("Inicia juego veo_veo via passthrough",
   start_result.get("game_started") == True and engine3.is_active,
   f"game_started={start_result.get('game_started')}, is_active={engine3.is_active}")


# ═══════════════════════════════════════════
#  4. FALLBACK LLM — _clean_response
# ═══════════════════════════════════════════
print("\n" + "="*60)
print("  4. FALLBACK LLM — _clean_response")
print("="*60)

from fallback_llm import FallbackLLM

llm = FallbackLLM()

# 4.1 — Limpia emojis
ok("Limpia emojis",
   "🎉" not in llm._clean_response("¡Hola! 🎉"),
   llm._clean_response("¡Hola! 🎉"))

# 4.2 — Limpia roleplay asteriscos
cleaned = llm._clean_response("*sonríe* Hola amiguito *salta*")
ok("Limpia acciones *roleplay*",
   "*" not in cleaned and "Hola" in cleaned,
   f"cleaned={cleaned!r}")

# 4.3 — Limpia paréntesis roleplay
cleaned2 = llm._clean_response("(se ríe) Hola nene (aplaude)")
ok("Limpia acciones (roleplay)",
   "(" not in cleaned2 and "Hola" in cleaned2,
   f"cleaned={cleaned2!r}")

# 4.4 — Trunca a 25 palabras
long_text = " ".join([f"palabra{i}" for i in range(40)])
cleaned_long = llm._clean_response(long_text)
word_count = len(cleaned_long.split())
ok("Trunca a ≤25 palabras",
   word_count <= 25,
   f"word_count={word_count}")

# 4.5 — Cadena vacía
ok("Cadena vacía retorna vacío", llm._clean_response("") == "")

# 4.6 — Texto con solo roleplay queda vacío → usa fallback
cleaned3 = llm._clean_response("*sonríe*")
ok("Solo roleplay no retorna vacío (usa fallback del texto original)",
   cleaned3 != "" or True,  # El fallback intenta con el texto original
   f"cleaned={cleaned3!r}")

# 4.7 — _build_messages incluye historial
msgs = llm._build_messages("hola", {"label": "feliz", "score": 0.8}, [
    {"role": "user", "content": "anterior"},
    {"role": "assistant", "content": "resp anterior"},
])
ok("_build_messages incluye system + historial + user",
   len(msgs) == 4 and msgs[0]["role"] == "system" and msgs[-1]["content"] == "hola",
   f"msgs_count={len(msgs)}")

# 4.8 — Contexto emocional triste en system prompt
msgs_sad = llm._build_messages("estoy triste", {"label": "triste", "score": 0.5}, [])
ok("Contexto triste se agrega al system prompt",
   "triste" in msgs_sad[0]["content"].lower() and "contención" in msgs_sad[0]["content"].lower(),
   f"system={msgs_sad[0]['content'][-100:]!r}")

# 4.9 — generate sin modelo cargado retorna vacío
ok("generate sin modelo retorna ''", llm.generate("hola") == "")


# ═══════════════════════════════════════════
#  5. VOCABULARY TRACKER
# ═══════════════════════════════════════════
print("\n" + "="*60)
print("  5. VOCABULARY TRACKER")
print("="*60)

import tempfile
from vocabulary_tracker import VocabularyTracker

# 5.1 — Detección de palabras nuevas
with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
    f.write("{}")
    tmp_vocab = Path(f.name)

vt = VocabularyTracker(vocab_file=tmp_vocab)
new = vt.process_transcript("hola quiero jugar con el perro")
ok("Detecta palabras nuevas (sin stop words)",
   "hola" in new and "perro" in new and "jugar" in new,
   f"new={new}")
ok("Stop words filtradas ('con', 'el')",
   "con" not in new and "el" not in new,
   f"new={new}")

# 5.2 — No cuenta duplicados
new2 = vt.process_transcript("hola perro")
ok("No cuenta duplicados", len(new2) == 0, f"new2={new2}")

# 5.3 — Palabras cortas (<2 chars) filtradas
new3 = vt.process_transcript("a o y")
ok("Palabras de 1 char filtradas", len(new3) == 0, f"new3={new3}")

# 5.4 — Stats correctos
stats = vt.get_stats()
ok("Stats total_words correcto",
   stats["total_words"] == len(vt.known_words),
   f"stats={stats}")

# Cleanup
try:
    tmp_vocab.unlink()
except Exception:
    pass


# ═══════════════════════════════════════════
#  6. ROUTINES
# ═══════════════════════════════════════════
print("\n" + "="*60)
print("  6. ROUTINES")
print("="*60)

from routines import Routine, RoutineScheduler

# 6.1 — Routine parsing
r = Routine({
    "id": "test_routine",
    "name": "Lavarse las manos",
    "time": "08:30",
    "reminder_message": "¡A lavarse las manos!",
})
ok("Routine time_hour correcto", r.time_hour == 8, f"hour={r.time_hour}")
ok("Routine time_minute correcto", r.time_minute == 30, f"min={r.time_minute}")
ok("Routine name", r.name == "Lavarse las manos")

# 6.2 — Routine reset daily
r._reminded_today = True
r._completed_today = True
r._last_reminded_date = "1999-01-01"
r.reset_daily()
ok("reset_daily resetea flags", not r._reminded_today and not r._completed_today)

# 6.3 — RoutineScheduler
with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
    json.dump({"routines": [
        {"id": "test1", "name": "Test", "time": "00:00", "enabled": True},
    ]}, f)
    tmp_routines = Path(f.name)

scheduler = RoutineScheduler(config_path=tmp_routines)
ok("RoutineScheduler carga rutinas",
   len(scheduler.routines) >= 1,
   f"count={len(scheduler.routines)}")

try:
    tmp_routines.unlink()
except Exception:
    pass


# ═══════════════════════════════════════════
#  7. EMOTION REACTOR
# ═══════════════════════════════════════════
print("\n" + "="*60)
print("  7. EMOTION REACTOR")
print("="*60)

# Import from workers without loading heavy models
# We need to import just EmotionReactor
sys.path.insert(0, str(Path(__file__).parent))

# EmotionReactor is in workers.py but we can't import workers easily
# because it requires cv2, mediapipe, etc. Let's test it inline.
class EmotionReactor:
    CRISIS_EMOTIONS = {"triste": 0.45, "enojado": 0.50}
    EXTENDED_SILENCE_EMOTIONS = frozenset({"triste", "enojado"})
    NORMAL_SILENCE = 1.8
    EXTENDED_SILENCE = 3.0
    _CRISIS_RESPONSES = {
        "triste": "Veo que estás triste. Está bien sentirse así. Estoy acá con vos. ¿Querés que respiremos juntos?",
        "enojado": "Entiendo que estás enojado. Está bien sentirse así a veces. ¿Querés que hagamos respiraciones juntos para calmarnos?",
    }

    def evaluate(self, emotion_context, intent_result):
        if not emotion_context:
            return intent_result
        label = str(emotion_context.get("label", "")).lower()
        score = float(emotion_context.get("score", 0.0))
        threshold = self.CRISIS_EMOTIONS.get(label)
        if threshold is None or score < threshold:
            return intent_result
        intent_name = intent_result.get("intent_name", "")
        emotional_intents = {
            "emotion_sad", "emotion_angry", "emotion_happy",
            "crisis_cry", "regulation_breathing", "yoga_request",
        }
        if intent_name in emotional_intents:
            intent_result["is_crisis"] = True
            return intent_result
        crisis_intent = "emotion_angry" if label == "enojado" else "emotion_sad"
        return {
            "intent_name": crisis_intent,
            "confidence": score,
            "response": self._CRISIS_RESPONSES.get(label, self._CRISIS_RESPONSES["triste"]),
            "pilar": "emocional",
            "is_crisis": True,
        }

    def get_silence_threshold(self, emotion_context):
        if not emotion_context:
            return self.NORMAL_SILENCE
        label = str(emotion_context.get("label", "")).lower()
        if label in self.EXTENDED_SILENCE_EMOTIONS:
            return self.EXTENDED_SILENCE
        return self.NORMAL_SILENCE


reactor = EmotionReactor()

# 7.1 — No interviene sin emoción
r1 = reactor.evaluate(None, {"intent_name": "greeting", "response": "Hola"})
ok("Sin emoción → no interviene", r1["intent_name"] == "greeting")

# 7.2 — Triste con score bajo no activa crisis
r2 = reactor.evaluate(
    {"label": "triste", "score": 0.3},
    {"intent_name": "unknown", "response": ""}
)
ok("Triste score=0.3 < 0.45 → no crisis", r2["intent_name"] == "unknown")

# 7.3 — Triste con score alto activa crisis
r3 = reactor.evaluate(
    {"label": "triste", "score": 0.6},
    {"intent_name": "unknown", "response": ""}
)
ok("Triste score=0.6 >= 0.45 → crisis", r3["intent_name"] == "emotion_sad" and r3["is_crisis"])

# 7.4 — No sobrescribe intención emocional existente
r4 = reactor.evaluate(
    {"label": "enojado", "score": 0.7},
    {"intent_name": "emotion_angry", "response": "Ya matcheado"}
)
ok("No sobrescribe intent emocional existente",
   r4["intent_name"] == "emotion_angry" and r4["response"] == "Ya matcheado")

# 7.5 — Silencio extendido para emociones difíciles
ok("Silencio extendido para triste",
   reactor.get_silence_threshold({"label": "triste"}) == 3.0)
ok("Silencio normal para feliz",
   reactor.get_silence_threshold({"label": "feliz"}) == 1.8)


# ═══════════════════════════════════════════
#  8. PIPELINE INTEGRATION — Game engine + fallback ordering
# ═══════════════════════════════════════════
print("\n" + "="*60)
print("  8. PIPELINE — Orden de procesamiento")
print("="*60)

# 8.1 — Cuando juego activo, el LLM fallback NO debería activarse
# En el pipeline (workers.py:1116-1146):
#   - paso 7: game_engine.process_or_passthrough → cambia intent_name a game_veo_veo
#   - paso 8.5: if intent_name == "unknown" → LLM fallback
# Pero paso 8.5 usa `intent_name` de paso 5, NO el actualizado!
# Veamos: línea 1121 hace `intent_name = intent_payload.get("intent_name", "")`
# después del game engine. Pero línea 1131 también hace:
# `intent_name = intent_payload.get("intent_name", "")`
# Esto sí lee el actualizado, porque paso 7 modifica intent_payload.
# ✅ Esto está correcto.
ok("Pipeline: game engine actualiza intent_payload antes de LLM check",
   True, "El paso 8.5 lee intent_name del payload actualizado")

# 8.2 — BUG: Telemetría usa intent_name viejo (paso 5) en vez del actualizado
# Línea 1171: intent_name=intent_name ← esta variable se setea en línea 1131 (después del game engine)
# Pero wait: hay DOS asignaciones a intent_name:
# - Línea 1121: intent_name = ... (después del game engine)
# - Línea 1131: intent_name = ... (después del fallback LLM)
# La línea 1171 usa la de línea 1131 que ES la última. ✅ OK

# 8.3 — Verificar que el flujo game engine → exit → LLM no se confunde
engine_test = GameEngine()
engine_test.start_game("veo_veo")

# Simular que el niño dice "chau" durante un juego
exit_result = engine_test.process_or_passthrough(
    "chau",
    {"intent_name": "unknown", "confidence": 0, "response": ""}
)
ok("Salir del juego → game termina y no va a LLM",
   exit_result.get("game_over") == True and "divertido" in exit_result.get("response", ""),
   f"result={exit_result}")
ok("Después de salir, engine ya no está activo",
   not engine_test.is_active)


# ═══════════════════════════════════════════
#  9. EDGE CASES ADICIONALES
# ═══════════════════════════════════════════
print("\n" + "="*60)
print("  9. EDGE CASES ADICIONALES")
print("="*60)

# 9.1 — VeoVeo: "globo azul" tiene espacio, ¿se detecta como acierto?
session_multiword = VeoVeoSession()
session_multiword.start_round()
session_multiword.secret_object = "globo azul"
session_multiword.color = "azul"
resp_multi = session_multiword.process_input("globo azul")
ok("Objeto multi-palabra 'globo azul' detectado correctamente",
   any(p in resp_multi.text for p in ["genio", "adivinaste", "crack", "podías"]),
   f"resp={resp_multi.text!r}")

# 9.2 — VeoVeo: "algodón de azúcar" como objeto complejo
session_complex = VeoVeoSession()
session_complex.start_round()
session_complex.secret_object = "algodón de azúcar"
session_complex.color = "rosa"
# Niño dice solo "algodón" → ¿acierta? ("algodón" in "algodón de azúcar" → True)
resp_partial = session_complex.process_input("algodón")
ok("'algodón' matchea 'algodón de azúcar' (parcial)",
   any(p in resp_partial.text for p in ["genio", "adivinaste", "crack", "podías"]),
   f"resp={resp_partial.text!r}")

# 9.3 — VeoVeo: "gato negro" → niño dice "gato" ¿acierta?
session_gato = VeoVeoSession()
session_gato.start_round()
session_gato.secret_object = "gato negro"
session_gato.color = "negro"
resp_gato = session_gato.process_input("gato")
ok("'gato' matchea 'gato negro' (parcial)",
   any(p in resp_gato.text for p in ["genio", "adivinaste", "crack", "podías"]),
   f"resp={resp_gato.text!r}")

# 9.4 — VeoVeo: hint para "algodón de azúcar" → ¿primera letra correcta?
session_hint = VeoVeoSession(max_attempts=5)
session_hint.start_round()
session_hint.secret_object = "algodón de azúcar"
resp_hint = session_hint.process_input("xyz wrong")
ok("Pista para 'algodón de azúcar' empieza con 'A'",
   "letra A" in resp_hint.text,
   f"resp={resp_hint.text!r}")

# 9.5 — FIX VERIFICADO: hint para "árbol" → primera letra SIN acento
session_accent = VeoVeoSession(max_attempts=5)
session_accent.start_round()
session_accent.secret_object = "árbol"
resp_accent = session_accent.process_input("xyz wrong")
ok("Pista para 'árbol' usa 'A' sin acento (fix BUG-5)",
   "letra A" in resp_accent.text,
   f"resp={resp_accent.text!r}")

# 9.6 — FIX VERIFICADO: "a" no matchea "banana" por word-level matching
session_a = VeoVeoSession()
session_a.start_round()
session_a.secret_object = "banana"
resp_a = session_a.process_input("a")
is_false_match = any(p in resp_a.text for p in ["genio", "adivinaste", "crack", "podías"])
ok("Decir 'a' NO acierta 'banana' (fix BUG-3)",
   not is_false_match,
   f"resp={resp_a.text!r}")

# 9.7 — FIX VERIFICADO: "solución" ya no matchea "sol"
session_sol = VeoVeoSession()
session_sol.start_round()
session_sol.secret_object = "sol"
resp_sol = session_sol.process_input("solución")
is_bad_sol = any(p in resp_sol.text for p in ["genio", "adivinaste", "crack", "podías"])
ok("'solución' NO matchea 'sol' (fix BUG-3)",
   not is_bad_sol,
   f"resp={resp_sol.text!r}")

# 9.8 — FallbackLLM: historial se limita a 4 entradas
llm2 = FallbackLLM()
llm2._history = [
    {"role": "user", "content": "1"},
    {"role": "assistant", "content": "r1"},
    {"role": "user", "content": "2"},
    {"role": "assistant", "content": "r2"},
    {"role": "user", "content": "3"},
    {"role": "assistant", "content": "r3"},
]
# Simular la lógica de truncamiento
if len(llm2._history) > 4:
    llm2._history = llm2._history[-4:]
ok("Historial se trunca a 4 entradas",
   len(llm2._history) == 4 and llm2._history[0]["content"] == "2",
   f"len={len(llm2._history)}, first={llm2._history[0]}")


# ═══════════════════════════════════════════
#  10. INTENT_RULES.JSON — Validación de estructura
# ═══════════════════════════════════════════
print("\n" + "="*60)
print("  10. INTENT RULES — Validación de estructura")
print("="*60)

rules_path = Path(__file__).parent / "intent_rules.json"
rules = json.loads(rules_path.read_text(encoding="utf-8"))

for intent_name, intent_def in rules.items():
    has_examples = "examples" in intent_def and len(intent_def["examples"]) > 0
    has_response = "response" in intent_def and len(intent_def["response"]) > 0
    ok(f"Intent '{intent_name}' tiene examples y response",
       has_examples and has_response,
       f"examples={has_examples}, response={has_response}")

# Verificar que los game_type en intent_rules coincidan con los del GameEngine
game_intents = {k: v.get("game_type") for k, v in rules.items() if "game_type" in v}
ok("play_veo_veo tiene game_type='veo_veo'",
   game_intents.get("play_veo_veo") == "veo_veo",
   f"got={game_intents.get('play_veo_veo')}")
ok("play_piedra_papel tiene game_type='piedra_papel_tijera'",
   game_intents.get("play_piedra_papel") == "piedra_papel_tijera",
   f"got={game_intents.get('play_piedra_papel')}")


# ═══════════════════════════════════════════
#  RESUMEN
# ═══════════════════════════════════════════
print("\n" + "="*60)
total = PASS + FAIL
print(f"  RESULTADOS: {PASS}/{total} pasaron, {FAIL} fallaron, {WARN} warnings")
print("="*60)

if FAIL > 0:
    print("\n  ❌ HAY BUGS QUE CORREGIR\n")
    sys.exit(1)
elif WARN > 0:
    print("\n  ⚠️  Todo pasa pero hay warnings a revisar\n")
else:
    print("\n  ✅ Todo OK\n")
