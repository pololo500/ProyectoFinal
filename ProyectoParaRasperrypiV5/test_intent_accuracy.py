"""test_intent_accuracy.py — Accuracy offline del IntentDispatcher.

Ejecutar con:  python test_intent_accuracy.py

No usa micrófono ni cámara. Carga intent_rules.json y mide cuántas
frases caen en el intent esperado (keyword vs unknown/LLM).
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
    ("hola", "greeting"),
    ("buenos dias teo", "greeting"),
    ("holi", "greeting"),
    ("que tal", "greeting"),
    ("hey hola", "unknown"),
    ("chau", "farewell"),
    ("me voy", "farewell"),
    ("nos vemos", "farewell"),
    ("adios teo", "farewell"),
    ("hola me llamo tomas", "unknown"),
    ("estoy triste", "unknown"),
    ("quiero llorar", "unknown"),
    ("me siento mal", "unknown"),
    ("estoy llorando", "unknown"),
    ("estoy enojado", "unknown"),
    ("me enoja", "unknown"),
    ("dejame", "unknown"),
    ("estoy furiosa", "unknown"),
    ("estoy feliz", "unknown"),
    ("estoy contento", "unknown"),
    ("que divertido", "unknown"),
    ("quiero a mama", "unknown"),
    ("quiero a mi papa", "unknown"),
    ("no puedo mas", "unknown"),
    ("no quiero estar solo", "unknown"),
    ("quiero respirar", "unknown"),
    ("ayudame a calmarme", "unknown"),
    ("estoy nervioso", "unknown"),
    ("hagamos yoga", "yoga_request"),
    ("quiero estirarme", "yoga_request"),
    ("juguemos veo veo", "play_veo_veo"),
    ("veo veo", "play_veo_veo"),
    ("dale veo veo", "play_veo_veo"),
    ("piedra papel o tijera", "play_piedra_papel"),
    ("juguemos piedra papel tijera", "play_piedra_papel"),
    ("quiero jugar al Piedra, papel o tijera", "play_piedra_papel"),
    ("paro la musica", "stop_music_request"),
    ("que es eso", "unknown"),
    ("como se llama", "unknown"),
    ("como te llamas", "identity_name"),
    ("quien sos", "identity_name"),
    ("por que", "unknown"),
    ("cantame una cancion", "song_request"),
    ("quiero musica", "song_request"),
    ("pone musica", "song_request"),
    ("ya termine", "unknown"),
    ("ya me lave", "unknown"),
    ("un ratito mas", "unknown"),
    ("cinco minutos mas", "unknown"),
    ("todavia no", "unknown"),
    ("ayudame", "unknown"),
    ("necesito ayuda", "unknown"),
    ("elijo este", "unknown"),
    ("quiero este", "unknown"),
    ("llama a mama", "call_parent"),
    ("quiero hablar con papa", "call_parent"),
    ("dame un abrazo", "hug_request"),
    ("abrazame", "hug_request"),
    ("te quiero", "unknown"),
    ("hay mucho ruido", "unknown"),
    ("me duelen los oidos", "unknown"),
    ("tengo miedo", "unknown"),
    ("estoy asustado", "unknown"),
    ("tengo cuco", "unknown"),
    ("tengo sueño", "unknown"),
    ("quiero dormir", "unknown"),
    ("no me sale", "unknown"),
    ("estoy frustrado", "unknown"),
    ("tengo hambre", "needs_basic"),
    ("quiero agua", "needs_basic"),
    ("tengo sed", "needs_basic"),
    ("quiero ir al baño", "unknown"),
    ("me lavo las manos", "unknown"),
    ("a guardar los juguetes", "unknown"),
    ("hay que ordenar", "unknown"),
    ("gracias teo", "unknown"),
    ("muchas gracias", "unknown"),
    ("contame un chiste", "unknown"),
    ("bailemos", "unknown"),
    ("hace frio", "unknown"),
    ("fui al jardin", "unknown"),
    ("mira lo que hice", "unknown"),
    ("me duele la panza", "unknown"),
    ("es mi cumple", "unknown"),
    ("quiero jugar", "unknown"),
    ("ola teo", "unknown"),
    ("kiero a mama", "unknown"),
    ("dame un abraso", "unknown"),
    ("cantame una cansión", "song_request"),
    ("tengo ambre", "unknown"),
    ("jugemos veo veo", "play_veo_veo"),
    ("estoy trsite", "unknown"),
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
    backend = "keyword" if dispatcher._sentence_model is None else "sentence-transformers"
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
