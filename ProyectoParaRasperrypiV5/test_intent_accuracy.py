"""test_intent_accuracy.py — Accuracy offline del IntentDispatcher.

Ejecutar con:  python test_intent_accuracy.py

No usa micrófono ni cámara. Carga intent_rules.json y mide cuántas
frases caen en el intent esperado. Sirve para calibrar MIN_CONFIDENCE
y CONFIDENCE_MARGIN.
"""
from __future__ import annotations

import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from unittest.mock import MagicMock

if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# IntentDispatcher vive en workers.py, que exige OpenCV/MediaPipe al importar.
sys.modules.setdefault("cv2", MagicMock())
sys.modules.setdefault("mediapipe", MagicMock())
sys.modules.setdefault("sounddevice", MagicMock())

from workers import IntentDispatcher

CASES: list[tuple[str, str]] = [
    # greeting
    ("hola", "greeting"),
    ("buenos dias teo", "greeting"),
    ("holi", "greeting"),
    ("que tal", "greeting"),
    ("hey hola", "greeting"),
    # farewell
    ("chau", "farewell"),
    ("me voy", "farewell"),
    ("nos vemos", "farewell"),
    ("adios teo", "farewell"),
    # emotion_sad
    ("estoy triste", "emotion_sad"),
    ("quiero llorar", "emotion_sad"),
    ("me siento mal", "emotion_sad"),
    ("estoy llorando", "emotion_sad"),
    # emotion_angry
    ("estoy enojado", "emotion_angry"),
    ("me enoja", "emotion_angry"),
    ("dejame", "emotion_angry"),
    ("estoy furiosa", "emotion_angry"),
    # emotion_happy
    ("estoy feliz", "emotion_happy"),
    ("estoy contento", "emotion_happy"),
    ("que divertido", "emotion_happy"),
    # crisis_cry (priority 20)
    ("quiero a mama", "crisis_cry"),
    ("quiero a mi papa", "crisis_cry"),
    ("no puedo mas", "crisis_cry"),
    ("no quiero estar solo", "crisis_cry"),
    # regulation / yoga
    ("quiero respirar", "regulation_breathing"),
    ("ayudame a calmarme", "regulation_breathing"),
    ("estoy nervioso", "regulation_breathing"),
    ("hagamos yoga", "yoga_request"),
    ("quiero estirarme", "yoga_request"),
    # games
    ("juguemos veo veo", "play_veo_veo"),
    ("veo veo", "play_veo_veo"),
    ("dale veo veo", "play_veo_veo"),
    ("piedra papel o tijera", "play_piedra_papel"),
    ("juguemos piedra papel tijera", "play_piedra_papel"),
    # curiosity
    ("que es eso", "question_curiosity"),
    ("como se llama", "question_curiosity"),
    ("por que", "question_curiosity"),
    # song
    ("cantame una cancion", "song_request"),
    ("quiero musica", "song_request"),
    ("pone musica", "song_request"),
    # routines
    ("ya termine", "routine_ack"),
    ("ya me lave", "routine_ack"),
    ("un ratito mas", "routine_resist"),
    ("cinco minutos mas", "routine_resist"),
    ("todavia no", "routine_resist"),
    ("ayudame", "help_request"),
    ("necesito ayuda", "help_request"),
    ("elijo este", "autonomy_decision"),
    ("quiero este", "autonomy_decision"),
    # parents / hug / sensory / fear
    ("llama a mama", "call_parent"),
    ("quiero hablar con papa", "call_parent"),
    ("dame un abrazo", "hug_request"),
    ("abrazame", "hug_request"),
    ("te quiero", "hug_request"),
    ("hay mucho ruido", "sensory_discomfort"),
    ("me duelen los oidos", "sensory_discomfort"),
    ("tengo miedo", "emotion_fear"),
    ("estoy asustado", "emotion_fear"),
    ("tengo cuco", "emotion_fear"),
    # tired / frustration / needs
    ("tengo sueño", "tired_sleepy"),
    ("quiero dormir", "tired_sleepy"),
    ("no me sale", "frustration_support"),
    ("estoy frustrado", "frustration_support"),
    ("tengo hambre", "needs_basic"),
    ("quiero agua", "needs_basic"),
    ("tengo sed", "needs_basic"),
    ("quiero ir al baño", "routine_hygiene"),
    ("me lavo las manos", "routine_hygiene"),
    ("a guardar los juguetes", "routine_tidy"),
    ("hay que ordenar", "routine_tidy"),
    ("gracias teo", "gratitude"),
    ("muchas gracias", "gratitude"),
    # typical whisper typos / child phrasing
    ("ola teo", "greeting"),
    ("kiero a mama", "crisis_cry"),
    ("dame un abraso", "hug_request"),
    ("cantame una cansión", "song_request"),
    ("tengo ambre", "needs_basic"),
    ("jugemos veo veo", "play_veo_veo"),
    ("estoy trsite", "emotion_sad"),
    # should fall through to unknown / LLM
    ("el gato fue a la luna", "unknown"),
    ("ayer vimos un dinosaurio enorme", "unknown"),
    ("mi mochila es azul con estrellas", "unknown"),
    ("cuanto es dos mas dos", "unknown"),
    ("me puse el sweater rojo", "unknown"),
]


def main() -> int:
    rules_path = Path(__file__).resolve().parent / "intent_rules.json"
    print("Cargando IntentDispatcher...")
    dispatcher = IntentDispatcher.from_file(rules_path)
    backend = "sentence-transformers" if dispatcher._sentence_model is not None else "spaCy fallback"
    print(f"Backend NLU: {backend}")
    print(f"MIN_CONFIDENCE={dispatcher.MIN_CONFIDENCE}  MARGIN={dispatcher.CONFIDENCE_MARGIN}")
    print(f"Casos: {len(CASES)}\n")

    correct = 0
    confusions: dict[tuple[str, str], int] = defaultdict(int)
    per_intent = Counter()
    per_intent_ok = Counter()

    for text, expected in CASES:
        result = dispatcher.dispatch(text)
        predicted = result.get("intent_name", "unknown")
        conf = float(result.get("confidence", 0.0))
        per_intent[expected] += 1
        ok = predicted == expected
        if ok:
            correct += 1
            per_intent_ok[expected] += 1
        else:
            confusions[(expected, predicted)] += 1
        mark = "OK" if ok else "FAIL"
        print(f"  [{mark}] {text!r:45} expected={expected:22} got={predicted:22} conf={conf:.3f}")

    accuracy = 100.0 * correct / len(CASES) if CASES else 0.0
    print("\n" + "=" * 60)
    print(f"Accuracy global: {correct}/{len(CASES)} = {accuracy:.1f}%")
    print("\nPor intent:")
    for intent in sorted(per_intent):
        total = per_intent[intent]
        ok_n = per_intent_ok[intent]
        print(f"  {intent:22} {ok_n}/{total}")

    if confusions:
        print("\nConfusiones (esperado → predicho):")
        for (expected, predicted), count in sorted(confusions.items(), key=lambda x: -x[1]):
            print(f"  {expected:22} → {predicted:22}  x{count}")

    # Keep a floor so regressions fail CI/local runs, but allow calibration.
    min_accuracy = 85.0
    if accuracy < min_accuracy:
        print(f"\nFALLA: accuracy {accuracy:.1f}% < {min_accuracy:.0f}%")
        return 1
    print(f"\nOK: accuracy {accuracy:.1f}% >= {min_accuracy:.0f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
