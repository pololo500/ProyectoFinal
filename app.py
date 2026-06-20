from __future__ import annotations

import argparse
import json
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

try:
    from PIL import Image, ImageTk
except ImportError:  # Optional dependency for frame rendering in Tkinter.
    Image = None
    ImageTk = None

from workers import AudioWorker, CameraWorker, IntentDispatcher, SpeechWorker, WorkerMessage, discover_cameras, discover_microphones, discover_output_devices


APP_DIR = Path(__file__).resolve().parent
INTENT_RULES_PATH = APP_DIR / "intent_rules.json"


# ---------------------------------------------------------------------------
# Subsystem lazy-loaders (telemetry, vocabulary, routines, eye display)
# ---------------------------------------------------------------------------

def _create_telemetry():
    """Create TelemetryCollector if module available."""
    try:
        from telemetry import TelemetryCollector
        return TelemetryCollector()
    except ImportError:
        return None


def _create_vocabulary_tracker():
    """Create VocabularyTracker if module available."""
    try:
        from vocabulary_tracker import VocabularyTracker
        return VocabularyTracker()
    except ImportError:
        return None


def _create_routine_scheduler():
    """Create RoutineScheduler if module available."""
    try:
        from routines import RoutineScheduler
        return RoutineScheduler()
    except ImportError:
        return None


# ═══════════════════════════════════════════════════════════════════════════
# EYE MODE APP — Pantalla de ojos expresivos (modo producción)
# ═══════════════════════════════════════════════════════════════════════════

class EyeModeApp(tk.Tk):
    """Interfaz minimalista de ojos expresivos para el peluche.

    Muestra solo los ojos animados en pantalla completa.  La emoción
    detectada por la cámara se refleja en la expresión de los ojos.
    Toda la información de debug se imprime en consola.

    Incluye controles de configuración sensorial (#EPIC-002):
    - Volumen máximo (slider)
    - Brillo de ojos (slider)
    Accesibles presionando la tecla 'C' (config).
    """

    def __init__(self) -> None:
        super().__init__()
        self.title("Edge AI — Configuración de Hardware")
        self.configure(bg="#1a1a2e")
        # Start windowed for device selection, go fullscreen after
        self.geometry("720x480")
        self.resizable(False, False)

        # Device discovery
        self.camera_options = discover_cameras()
        self.microphone_options = discover_microphones()
        self.output_device_options = discover_output_devices()

        self.message_queue: queue.Queue[WorkerMessage] = queue.Queue(maxsize=512)
        self.message_queue_semaphore = threading.BoundedSemaphore(512)
        self.frame_queue_semaphore = threading.BoundedSemaphore(2)
        self.frame_queue: queue.Queue[object] = queue.Queue(maxsize=2)
        self.camera_worker: CameraWorker | None = None
        self.audio_worker: AudioWorker | None = None
        self.intent_dispatcher: IntentDispatcher | None = None
        self.speech_worker: SpeechWorker | None = None

        # Subsystems
        self.telemetry = _create_telemetry()
        self.vocabulary_tracker = _create_vocabulary_tracker()
        self.routine_scheduler = _create_routine_scheduler()

        # Volume limit (0-100)
        self._volume_limit: int = 100
        self._brightness: float = 1.0

        # Eye display (created later, after device selection)
        self.eye_canvas: tk.Canvas | None = None
        self._eye_display = None

        # Config panel (hidden by default)
        self._config_visible = False
        self._config_frame: tk.Frame | None = None

        # Show the device selection screen first
        self._build_device_selector()

        # Polling starts immediately (no-op until workers are running)
        self.after(30, self._poll_queues)

    # ------------------------------------------------------------------
    # Device selection screen (shown before the eyes)
    # ------------------------------------------------------------------

    def _build_device_selector(self) -> None:
        """Build the temporary hardware selection UI."""
        self._setup_frame = tk.Frame(self, bg="#1a1a2e", padx=40, pady=30)
        self._setup_frame.place(relx=0.5, rely=0.5, anchor="center")

        # Title
        tk.Label(
            self._setup_frame,
            text="🎮 Configuración de Hardware",
            fg="#e0f7fa", bg="#1a1a2e",
            font=("Segoe UI", 20, "bold"),
        ).grid(row=0, column=0, columnspan=2, pady=(0, 8))

        tk.Label(
            self._setup_frame,
            text="Seleccioná los dispositivos a usar y presioná Iniciar.",
            fg="#90a4ae", bg="#1a1a2e",
            font=("Segoe UI", 11),
        ).grid(row=1, column=0, columnspan=2, pady=(0, 24))

        label_style = {"fg": "#b0bec5", "bg": "#1a1a2e", "font": ("Segoe UI", 12)}
        combo_style = {"font": ("Segoe UI", 11), "state": "readonly"}

        # Camera
        tk.Label(self._setup_frame, text="📷  Cámara:", **label_style).grid(
            row=2, column=0, sticky="w", pady=8, padx=(0, 16),
        )
        camera_values = [label for _, label in self.camera_options] or ["No se detectaron cámaras"]
        self._sel_camera_var = tk.StringVar()
        self._sel_camera_combo = ttk.Combobox(
            self._setup_frame, textvariable=self._sel_camera_var,
            values=camera_values, width=44, **combo_style,
        )
        self._sel_camera_combo.grid(row=2, column=1, sticky="we", pady=8)
        if camera_values:
            self._sel_camera_combo.current(0)

        # Microphone
        tk.Label(self._setup_frame, text="🎤  Micrófono:", **label_style).grid(
            row=3, column=0, sticky="w", pady=8, padx=(0, 16),
        )
        mic_values = [label for _, label in self.microphone_options] or ["No se detectaron micrófonos"]
        self._sel_mic_var = tk.StringVar()
        self._sel_mic_combo = ttk.Combobox(
            self._setup_frame, textvariable=self._sel_mic_var,
            values=mic_values, width=44, **combo_style,
        )
        self._sel_mic_combo.grid(row=3, column=1, sticky="we", pady=8)
        if mic_values:
            self._sel_mic_combo.current(0)

        # Speaker
        tk.Label(self._setup_frame, text="🔊  Parlante:", **label_style).grid(
            row=4, column=0, sticky="w", pady=8, padx=(0, 16),
        )
        out_values = [label for _, label in self.output_device_options] or ["Salida predeterminada"]
        self._sel_out_var = tk.StringVar()
        self._sel_out_combo = ttk.Combobox(
            self._setup_frame, textvariable=self._sel_out_var,
            values=out_values, width=44, **combo_style,
        )
        self._sel_out_combo.grid(row=4, column=1, sticky="we", pady=8)
        if out_values:
            self._sel_out_combo.current(0)

        # --- Test buttons ---
        test_frame = tk.Frame(self._setup_frame, bg="#1a1a2e")
        test_frame.grid(row=5, column=0, columnspan=2, pady=(8, 0))

        self._test_mic_btn = tk.Button(
            test_frame, text="🎤 Probar Micrófono",
            font=("Segoe UI", 10), bg="#37474f", fg="white",
            activebackground="#455a64", activeforeground="white",
            relief="flat", padx=12, pady=4,
            command=self._test_microphone_setup,
        )
        self._test_mic_btn.pack(side="left", padx=(0, 12))

        self._test_spk_btn = tk.Button(
            test_frame, text="🔊 Probar Parlante",
            font=("Segoe UI", 10), bg="#37474f", fg="white",
            activebackground="#455a64", activeforeground="white",
            relief="flat", padx=12, pady=4,
            command=self._test_speaker_setup,
        )
        self._test_spk_btn.pack(side="left")

        # Status label
        self._setup_status_var = tk.StringVar(value="")
        tk.Label(
            self._setup_frame, textvariable=self._setup_status_var,
            fg="#80cbc4", bg="#1a1a2e", font=("Segoe UI", 10),
        ).grid(row=6, column=0, columnspan=2, pady=(8, 0))

        # Start button
        self._start_btn = tk.Button(
            self._setup_frame,
            text="▶  Iniciar",
            font=("Segoe UI", 14, "bold"),
            bg="#00897b", fg="white",
            activebackground="#00695c", activeforeground="white",
            relief="flat", padx=32, pady=10,
            cursor="hand2",
            command=self._on_start_pressed,
        )
        self._start_btn.grid(row=7, column=0, columnspan=2, pady=(24, 0))

    def _get_selected_camera_idx(self) -> int:
        if not self.camera_options:
            return 0
        idx = self._sel_camera_combo.current()
        return self.camera_options[max(0, idx)][0]

    def _get_selected_mic_idx(self) -> int | None:
        if not self.microphone_options:
            return None
        idx = self._sel_mic_combo.current()
        return self.microphone_options[max(0, idx)][0]

    def _get_selected_out_idx(self) -> int | None:
        if not self.output_device_options:
            return None
        idx = self._sel_out_combo.current()
        return self.output_device_options[max(0, idx)][0]

    def _test_microphone_setup(self) -> None:
        """Record 3s from selected mic and play back through selected speaker."""
        mic_idx = self._get_selected_mic_idx()
        out_idx = self._get_selected_out_idx()
        if mic_idx is None:
            self._setup_status_var.set("⚠ No hay micrófono seleccionado")
            return

        self._setup_status_var.set("🎤 Grabando 3 segundos...")
        self._test_mic_btn.configure(state="disabled")

        def _run() -> None:
            try:
                import numpy as np
                import sounddevice as sd
                sr = 16000
                recorded = sd.rec(sr * 3, samplerate=sr, channels=1, dtype="float32", device=mic_idx)
                sd.wait()
                self.after(0, lambda: self._setup_status_var.set("🔊 Reproduciendo..."))
                sd.play(recorded[:, 0], samplerate=sr, device=out_idx)
                sd.wait()
                self.after(0, lambda: self._setup_status_var.set("✅ Prueba de micrófono completada"))
            except Exception as exc:
                self.after(0, lambda e=exc: self._setup_status_var.set(f"❌ Error: {e}"))
            finally:
                self.after(0, lambda: self._test_mic_btn.configure(state="normal"))

        threading.Thread(target=_run, daemon=True).start()

    def _test_speaker_setup(self) -> None:
        """Play a 440Hz beep on the selected speaker."""
        out_idx = self._get_selected_out_idx()
        self._setup_status_var.set("🔊 Reproduciendo tono de prueba...")
        self._test_spk_btn.configure(state="disabled")

        def _run() -> None:
            try:
                import numpy as np
                import sounddevice as sd
                sr = 44100
                t = np.linspace(0, 0.8, int(sr * 0.8), False)
                tone = (np.sin(440 * t * 2 * np.pi) * np.linspace(1, 0, len(t)) * 0.5).astype(np.float32)
                sd.play(tone, samplerate=sr, device=out_idx)
                sd.wait()
                self.after(0, lambda: self._setup_status_var.set("✅ Prueba de parlante completada"))
            except Exception as exc:
                self.after(0, lambda e=exc: self._setup_status_var.set(f"❌ Error: {e}"))
            finally:
                self.after(0, lambda: self._test_spk_btn.configure(state="normal"))

        threading.Thread(target=_run, daemon=True).start()

    def _on_start_pressed(self) -> None:
        """Transition from device selection to fullscreen eye display."""
        cam_idx = self._get_selected_camera_idx()
        mic_idx = self._get_selected_mic_idx()
        out_idx = self._get_selected_out_idx()

        if mic_idx is None:
            self._setup_status_var.set("⚠ Necesitás al menos un micrófono para continuar")
            return

        # Destroy setup UI
        self._setup_frame.destroy()
        self._setup_frame = None

        # Go fullscreen and create eye display
        self.title("Edge AI — Ojos")
        self.geometry("")  # reset geometry constraints
        self.resizable(True, True)
        self.attributes("-fullscreen", True)

        # Keybindings for fullscreen mode
        self.bind("<Escape>", lambda e: self.attributes("-fullscreen", False))
        self.bind("<F11>", lambda e: self.attributes(
            "-fullscreen", not self.attributes("-fullscreen")
        ))
        self.bind("<c>", lambda e: self._toggle_config_panel())
        self.bind("<C>", lambda e: self._toggle_config_panel())

        # Create eye canvas
        self.eye_canvas = tk.Canvas(self, bg="#1a1a2e", highlightthickness=0)
        self.eye_canvas.pack(fill="both", expand=True)

        try:
            from eye_display import EyeDisplay
            self._eye_display = EyeDisplay(self.eye_canvas)
        except ImportError:
            self.eye_canvas.create_text(
                400, 240, text="👀", font=("Segoe UI Emoji", 120),
                fill="white",
            )

        # Start workers with the selected devices
        self._start_workers(cam_idx, mic_idx, out_idx)

        # Start routine check timer
        self.after(30000, self._check_routines)

    def _start_workers(self, cam_idx: int, mic_idx: int, out_idx: int | None) -> None:
        """Initialize and start all workers with the selected devices."""
        try:
            self.intent_dispatcher = IntentDispatcher.from_file(INTENT_RULES_PATH)
        except Exception as exc:
            print(f"[EyeMode] ERROR NLU: {exc}", flush=True)
            return

        self.speech_worker = SpeechWorker(
            output_device_index=out_idx,
            message_queue=self.message_queue,
            message_semaphore=self.message_queue_semaphore,
        )
        self.speech_worker.start()

        self.camera_worker = CameraWorker(
            camera_index=cam_idx,
            frame_queue=self.frame_queue,
            frame_semaphore=self.frame_queue_semaphore,
            message_queue=self.message_queue,
            message_semaphore=self.message_queue_semaphore,
        )
        self.audio_worker = AudioWorker(
            microphone_device_index=mic_idx,
            message_queue=self.message_queue,
            message_semaphore=self.message_queue_semaphore,
            intent_dispatcher=self.intent_dispatcher,
            camera_ready_event=self.camera_worker.models_loaded_event,
            speech_worker=self.speech_worker,
            telemetry=self.telemetry,
            vocabulary_tracker=self.vocabulary_tracker,
            routine_scheduler=self.routine_scheduler,
        )

        self.camera_worker.start()
        self.audio_worker.start()
        print("[EyeMode] Workers iniciados", flush=True)

    # ------------------------------------------------------------------
    # Config panel (accessible via 'C' key during eye display)
    # ------------------------------------------------------------------

    def _toggle_config_panel(self) -> None:
        """Show/hide the sensory configuration panel."""
        if self._config_visible and self._config_frame is not None:
            self._config_frame.destroy()
            self._config_frame = None
            self._config_visible = False
            return

        self._config_visible = True
        self._config_frame = tk.Frame(
            self, bg="#2d2d4e", padx=20, pady=20, relief="raised", bd=2,
        )
        self._config_frame.place(relx=0.5, rely=0.9, anchor="center")

        # Volume slider
        tk.Label(
            self._config_frame, text="🔊 Volumen máximo:",
            fg="white", bg="#2d2d4e", font=("Segoe UI", 11),
        ).grid(row=0, column=0, sticky="w", padx=(0, 10))

        vol_var = tk.IntVar(value=self._volume_limit)
        tk.Scale(
            self._config_frame, from_=0, to=100, orient="horizontal",
            variable=vol_var, bg="#2d2d4e", fg="white", highlightthickness=0,
            length=200, command=lambda v: self._set_volume_limit(int(v)),
        ).grid(row=0, column=1, padx=(0, 20))

        # Brightness slider
        tk.Label(
            self._config_frame, text="💡 Brillo ojos:",
            fg="white", bg="#2d2d4e", font=("Segoe UI", 11),
        ).grid(row=0, column=2, sticky="w", padx=(0, 10))

        bright_var = tk.IntVar(value=int(self._brightness * 100))
        tk.Scale(
            self._config_frame, from_=0, to=100, orient="horizontal",
            variable=bright_var, bg="#2d2d4e", fg="white", highlightthickness=0,
            length=200, command=lambda v: self._set_brightness(int(v) / 100.0),
        ).grid(row=0, column=3)

    def _set_volume_limit(self, value: int) -> None:
        self._volume_limit = value

    def _set_brightness(self, value: float) -> None:
        self._brightness = value
        if self._eye_display is not None:
            self._eye_display.set_brightness(value)

    def _poll_queues(self) -> None:
        try:
            while True:
                message = self.message_queue.get_nowait()
                try:
                    self._handle_message(message)
                finally:
                    self.message_queue_semaphore.release()
        except queue.Empty:
            pass

        # Discard frames in eye mode (we don't render video)
        try:
            while True:
                self.frame_queue.get_nowait()
                self.frame_queue_semaphore.release()
        except queue.Empty:
            pass

        self.after(30, self._poll_queues)

    def _handle_message(self, message: WorkerMessage) -> None:
        if message.kind == "log":
            print(f"[LOG] {message.payload}", flush=True)
        elif message.kind == "emotion":
            payload = message.payload or {}
            label = payload.get("label")
            if label and self._eye_display is not None:
                self._eye_display.set_expression(label)
            # Update intent dispatcher
            try:
                if self.intent_dispatcher is not None:
                    if label is None:
                        self.intent_dispatcher.set_current_emotion(None)
                    else:
                        self.intent_dispatcher.set_current_emotion(
                            str(label), float(payload.get("score", 0.0))
                        )
            except Exception:
                pass
        elif message.kind == "transcript":
            payload = message.payload
            print(f"[TRANSCRIPT] {payload.get('raw_text', '')}", flush=True)
            intent = payload.get("intent", {})
            print(
                f"[INTENT] {intent.get('intent_name', '?')} "
                f"(conf={intent.get('confidence', 0):.3f}) "
                f"→ {intent.get('response', '')}",
                flush=True,
            )
            new_words = payload.get("new_words", [])
            if new_words:
                print(f"[VOCAB] Nuevas: {', '.join(new_words)}", flush=True)

            # Set eyes to "hablando" when TTS will play
            if intent.get("response") and self._eye_display is not None:
                self._eye_display.set_expression("hablando")
                # Restore previous expression after a delay
                self.after(3000, lambda: self._eye_display.set_expression(
                    self._eye_display.get_expression()
                    if self._eye_display.get_expression() != "hablando"
                    else "neutral"
                ))

    def _check_routines(self) -> None:
        """Periodic check for routine reminders."""
        if self.routine_scheduler is not None and self.speech_worker is not None:
            try:
                messages = self.routine_scheduler.check_pending()
                for msg in messages:
                    print(f"[ROUTINE] {msg}", flush=True)
                    self.speech_worker.speak(msg)
            except Exception:
                pass
        self.after(30000, self._check_routines)

    def stop_workers(self) -> None:
        if self.camera_worker:
            self.camera_worker.stop()
            self.camera_worker = None
        if self.audio_worker:
            self.audio_worker.stop()
            self.audio_worker = None
        if self.speech_worker:
            self.speech_worker.stop()
            self.speech_worker = None

    def on_close(self) -> None:
        self.stop_workers()
        self.destroy()


# ═══════════════════════════════════════════════════════════════════════════
# DEBUG MODE APP — Panel completo de desarrollo (UI original)
# ═══════════════════════════════════════════════════════════════════════════

class EdgeAiDesktopApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Edge AI PoC — Modo Debug")
        self.geometry("1280x820")
        self.minsize(1100, 720)

        self.camera_options = discover_cameras()
        self.microphone_options = discover_microphones()
        self.output_device_options = discover_output_devices()

        self.message_queue: queue.Queue[WorkerMessage] = queue.Queue(maxsize=512)
        self.message_queue_semaphore = threading.BoundedSemaphore(512)
        self.frame_queue_semaphore = threading.BoundedSemaphore(2)
        self.frame_queue: queue.Queue[object] = queue.Queue(maxsize=2)
        self.camera_worker: CameraWorker | None = None
        self.audio_worker: AudioWorker | None = None
        self.intent_dispatcher: IntentDispatcher | None = None
        self.speech_worker: SpeechWorker | None = None
        self._mic_test_stop = threading.Event()
        self._mic_test_thread: threading.Thread | None = None

        # Subsystems
        self.telemetry = _create_telemetry()
        self.vocabulary_tracker = _create_vocabulary_tracker()
        self.routine_scheduler = _create_routine_scheduler()

        self._current_photo = None
        
        self._camera_desc = "inactiva"
        self._detected_state = "ninguno"
        self._mic_desc = "inactivo"
        self._mic_volume_pct = 0

        self._build_ui()
        self._refresh_device_labels()
        self.after(30, self._poll_queues)

        # Routine check timer
        self.after(30000, self._check_routines)

    def _build_ui(self) -> None:
        self.configure(bg="#0f172a")

        header = ttk.Frame(self, padding=12)
        header.pack(fill="x")

        title = ttk.Label(header, text="Sistema Edge AI Interactivo - PoC (Debug)", font=("Segoe UI", 18, "bold"))
        title.pack(anchor="w")

        subtitle = ttk.Label(
            header,
            text="Selecciona cámara y micrófono, luego inicia la captura. La carga de modelos se hace solo después.",
        )
        subtitle.pack(anchor="w", pady=(4, 0))

        controls = ttk.LabelFrame(self, text="Selector de Hardware", padding=12)
        controls.pack(fill="x", padx=12, pady=(0, 12))

        self.camera_var = tk.StringVar()
        self.microphone_var = tk.StringVar()
        self.output_device_var = tk.StringVar()

        ttk.Label(controls, text="Cámara:").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        self.camera_combo = ttk.Combobox(controls, textvariable=self.camera_var, state="readonly", width=56)
        self.camera_combo.grid(row=0, column=1, sticky="we", pady=4)

        ttk.Label(controls, text="Micrófono:").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)

        mic_frame = ttk.Frame(controls)
        mic_frame.grid(row=1, column=1, sticky="we", pady=4)
        self.microphone_combo = ttk.Combobox(mic_frame, textvariable=self.microphone_var, state="readonly")
        self.microphone_combo.pack(side="left", fill="x", expand=True)

        self.test_mic_button = ttk.Button(mic_frame, text="Probar", command=self._test_microphone, width=8)
        self.test_mic_button.pack(side="left", padx=(8, 0))

        ttk.Label(controls, text="Parlante:").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=4)
        
        speaker_frame = ttk.Frame(controls)
        speaker_frame.grid(row=2, column=1, sticky="we", pady=4)
        self.output_device_combo = ttk.Combobox(speaker_frame, textvariable=self.output_device_var, state="readonly")
        self.output_device_combo.pack(side="left", fill="x", expand=True)
        
        self.test_audio_button = ttk.Button(speaker_frame, text="Probar", command=self._test_audio_output, width=8)
        self.test_audio_button.pack(side="left", padx=(8, 0))

        # --- Sensory config row (#EPIC-002) ---
        ttk.Label(controls, text="Vol. máx:").grid(row=3, column=0, sticky="w", padx=(0, 8), pady=4)
        self._volume_var = tk.IntVar(value=100)
        vol_scale = ttk.Scale(controls, from_=0, to=100, variable=self._volume_var, orient="horizontal")
        vol_scale.grid(row=3, column=1, sticky="we", pady=4)

        controls.columnconfigure(1, weight=1)

        actions = ttk.Frame(controls)
        actions.grid(row=0, column=2, rowspan=4, padx=(14, 0), sticky="ns")

        self.start_button = ttk.Button(actions, text="Iniciar", command=self.start_workers)
        self.start_button.pack(fill="x", pady=(0, 8))

        self.stop_button = ttk.Button(actions, text="Detener", command=self.stop_workers, state="disabled")
        self.stop_button.pack(fill="x")

        body = ttk.Frame(self, padding=(12, 0, 12, 12))
        body.pack(fill="both", expand=True)

        vision_frame = ttk.LabelFrame(body, text="Panel de Visión", padding=10)
        vision_frame.pack(side="left", fill="both", expand=True, padx=(0, 10))

        self.video_panel = ttk.Label(vision_frame, text="Vista de cámara pendiente de selección", anchor="center")
        self.video_panel.pack(fill="both", expand=True)

        logs_frame = ttk.LabelFrame(body, text="Logs y Procesamiento en Tiempo Real", padding=10)
        logs_frame.pack(side="right", fill="both", expand=True)

        self.status_var = tk.StringVar(value="Estado: esperando selección de hardware")
        ttk.Label(logs_frame, textvariable=self.status_var).pack(anchor="w", pady=(0, 8))

        self.log_text = tk.Text(logs_frame, wrap="word", height=28, background="#111827", foreground="#e5e7eb", insertbackground="#e5e7eb")
        self.log_text.pack(fill="both", expand=True, side="left")

        scrollbar = ttk.Scrollbar(logs_frame, command=self.log_text.yview)
        scrollbar.pack(fill="y", side="right")
        self.log_text.configure(yscrollcommand=scrollbar.set)

        self.log_text.insert("end", "La interfaz está lista. Selecciona hardware para inicializar los workers.\n")
        self.log_text.configure(state="disabled")

    def _refresh_device_labels(self) -> None:
        camera_values = [label for _, label in self.camera_options] or ["No se detectaron cámaras"]
        microphone_values = [label for _, label in self.microphone_options] or ["No se detectaron micrófonos"]
        output_values = [label for _, label in self.output_device_options] or ["Salida predeterminada"]

        self.camera_combo["values"] = camera_values
        self.microphone_combo["values"] = microphone_values
        self.output_device_combo["values"] = output_values

        if camera_values:
            self.camera_combo.current(0)
        if microphone_values:
            self.microphone_combo.current(0)
        if output_values:
            self.output_device_combo.current(0)

    def _selected_camera(self) -> int:
        if not self.camera_options:
            raise RuntimeError("No hay cámaras disponibles")
        index = self.camera_combo.current()
        return self.camera_options[index][0]

    def _selected_microphone(self) -> int:
        if not self.microphone_options:
            raise RuntimeError("No hay micrófonos disponibles")
        index = self.microphone_combo.current()
        return self.microphone_options[index][0]

    def _selected_output_device(self) -> int | None:
        if not self.output_device_options:
            return None
        index = self.output_device_combo.current()
        if index < 0 or index >= len(self.output_device_options):
            return None
        return self.output_device_options[index][0]

    def _test_audio_output(self) -> None:
        try:
            device_index = self._selected_output_device()
            
            def play_beep() -> None:
                try:
                    import numpy as np
                    import sounddevice as sd
                    sample_rate = 44100
                    t = np.linspace(0, 1, sample_rate, False)
                    note = np.sin(440 * t * 2 * np.pi)
                    note *= np.linspace(1, 0, sample_rate)
                    audio = (note * 32767).astype(np.int16)
                    sd.play(audio, samplerate=sample_rate, device=device_index)
                    sd.wait()
                except Exception:
                    pass

            threading.Thread(target=play_beep, daemon=True).start()
            self._append_log("Reproduciendo sonido de prueba (tono de 440Hz)...")
        except Exception as exc:
            messagebox.showerror("Error", f"No se pudo probar el audio: {exc}")

    def _test_microphone(self) -> None:
        """Toggle mic loopback: record from mic and play through speaker for testing."""
        # If already running, stop it
        if self._mic_test_thread is not None and self._mic_test_thread.is_alive():
            self._mic_test_stop.set()
            self.test_mic_button.configure(text="Probar")
            self._append_log("Prueba de micrófono detenida.")
            return

        try:
            mic_index = self._selected_microphone()
            out_index = self._selected_output_device()
        except Exception as exc:
            messagebox.showerror("Error", f"No se pudo obtener dispositivos: {exc}")
            return

        self._mic_test_stop.clear()
        record_seconds = 3

        def _loopback() -> None:
            try:
                import numpy as np
                import sounddevice as sd

                sample_rate = 16000
                total_samples = sample_rate * record_seconds
                self.after(0, lambda: self._append_log(
                    f"Grabando {record_seconds}s desde micrófono..."
                ))

                recorded = sd.rec(
                    total_samples,
                    samplerate=sample_rate,
                    channels=1,
                    dtype="float32",
                    device=mic_index,
                )
                # Wait for recording, checking stop flag periodically
                elapsed = 0.0
                while elapsed < record_seconds and not self._mic_test_stop.is_set():
                    sd.sleep(100)
                    elapsed += 0.1

                if self._mic_test_stop.is_set():
                    sd.stop()
                    return

                sd.wait()  # Ensure recording is complete
                audio = recorded[:, 0]

                self.after(0, lambda: self._append_log(
                    "Reproduciendo grabación por parlante..."
                ))
                sd.play(audio, samplerate=sample_rate, device=out_index)
                sd.wait()

                self.after(0, lambda: self._append_log(
                    "Prueba de micrófono completada."
                ))
            except Exception as exc:
                self.after(0, lambda e=exc: self._append_log(
                    f"Error en prueba de micrófono: {e}"
                ))
            finally:
                self.after(0, lambda: self.test_mic_button.configure(text="Probar"))

        self.test_mic_button.configure(text="Detener")
        self._append_log(f"Iniciando prueba de micrófono (graba {record_seconds}s y reproduce)...")
        self._mic_test_thread = threading.Thread(target=_loopback, daemon=True)
        self._mic_test_thread.start()

    def start_workers(self) -> None:
        if self.camera_worker or self.audio_worker:
            return

        try:
            camera_index = self._selected_camera()
            microphone_index = self._selected_microphone()
            output_device_index = self._selected_output_device()
        except Exception as exc:
            messagebox.showerror("Hardware no disponible", str(exc))
            return

        try:
            self.intent_dispatcher = IntentDispatcher.from_file(INTENT_RULES_PATH)
        except Exception as exc:
            messagebox.showerror("Error de NLU", f"No se pudo inicializar spaCy o las reglas de intención: {exc}")
            self.intent_dispatcher = None
            return

        self.speech_worker = SpeechWorker(
            output_device_index=output_device_index,
            message_queue=self.message_queue,
            message_semaphore=self.message_queue_semaphore,
        )
        self.speech_worker.start()

        self._camera_desc = "inactiva"
        self._detected_state = "ninguno"
        self._mic_desc = "inactivo"
        self._mic_volume_pct = 0

        self._append_log(f"Iniciando workers con cámara {camera_index} y micrófono {microphone_index}")
        self.status_var.set("Estado: inicializando workers")

        self.camera_worker = CameraWorker(
            camera_index=camera_index,
            frame_queue=self.frame_queue,
            frame_semaphore=self.frame_queue_semaphore,
            message_queue=self.message_queue,
            message_semaphore=self.message_queue_semaphore,
        )
        self.audio_worker = AudioWorker(
            microphone_device_index=microphone_index,
            message_queue=self.message_queue,
            message_semaphore=self.message_queue_semaphore,
            intent_dispatcher=self.intent_dispatcher,
            camera_ready_event=self.camera_worker.models_loaded_event,
            speech_worker=self.speech_worker,
            telemetry=self.telemetry,
            vocabulary_tracker=self.vocabulary_tracker,
            routine_scheduler=self.routine_scheduler,
        )

        self.camera_worker.start()
        self.audio_worker.start()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")

    def stop_workers(self) -> None:
        if self.camera_worker:
            self.camera_worker.stop()
            self.camera_worker = None
        if self.audio_worker:
            self.audio_worker.stop()
            self.audio_worker = None
        if self.speech_worker:
            self.speech_worker.stop()
            self.speech_worker = None

        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        
        self._camera_desc = "inactiva"
        self._detected_state = "ninguno"
        self._mic_desc = "inactivo"
        self._mic_volume_pct = 0
        
        self.status_var.set("Estado: detenido")
        self._append_log("Workers detenidos correctamente")

    def _append_log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{text}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _update_status_text(self) -> None:
        status_parts = []
        
        # Camera part
        if self._camera_desc != "inactiva" and self._camera_desc != "error":
            status_parts.append(f"cámara {self._camera_desc}")
        else:
            status_parts.append(f"cámara {self._camera_desc}")
            
        # Emotion/Detected state part
        if self._detected_state and self._detected_state != "ninguno":
            status_parts.append(f"Estado detectado: {self._detected_state}")
            
        # Mic part
        if self._mic_desc != "inactivo" and self._mic_desc != "error":
            status_parts.append(f"micrófono {self._mic_desc}")
            status_parts.append(f"Volumen micrófono: {self._mic_volume_pct}%")
        else:
            status_parts.append(f"micrófono {self._mic_desc}")
            
        self.status_var.set("Estado: " + " | ".join(status_parts))

    def _render_frame(self, frame: object) -> None:
        if Image is None or ImageTk is None:
            self.video_panel.configure(text="Pillow no está instalado, no se puede renderizar el video.")
            return

        try:
            pil_image = Image.fromarray(frame)
            panel_width = max(self.video_panel.winfo_width(), 640)
            panel_height = max(self.video_panel.winfo_height(), 480)
            pil_image.thumbnail((panel_width, panel_height))
            self._current_photo = ImageTk.PhotoImage(image=pil_image)
            self.video_panel.configure(image=self._current_photo, text="")
        except Exception as exc:
            self._append_log(f"Error al renderizar frame: {exc}")

    def _handle_worker_message(self, message: WorkerMessage) -> None:
        if message.kind == "log":
            self._append_log(str(message.payload))
        elif message.kind == "status":
            payload = message.payload
            if isinstance(payload, dict):
                if "camera" in payload:
                    self._camera_desc = payload["camera"]
                if "emotion" in payload:
                    self._detected_state = payload["emotion"]
                if "mic" in payload:
                    self._mic_desc = payload["mic"]
                if "volume" in payload:
                    self._mic_volume_pct = payload["volume"]
                self._update_status_text()
            else:
                self.status_var.set(str(payload))
        elif message.kind == "frame":
            self._render_frame(message.payload)
        elif message.kind == "emotion":
            payload = message.payload or {}
            label = payload.get('label')
            score = float(payload.get('score', 0.0))
            # Update intent dispatcher with latest emotion context so NLU
            # can consider it when matching intents. This keeps response
            # processing independent and immediate.
            try:
                if self.intent_dispatcher is not None:
                    if label is None:
                        self.intent_dispatcher.set_current_emotion(None)
                    else:
                        self.intent_dispatcher.set_current_emotion(str(label), score)
            except Exception:
                pass
        elif message.kind == "transcript":
            payload = message.payload
            self._append_log(f"Texto crudo transcrito: {payload.get('raw_text', '')}")
            self._append_log(f"Texto sanitizado: {json.dumps(payload.get('sanitized', {}), ensure_ascii=False)}")
            emotion_info = payload.get("emotion") or {}
            self._append_log(
                "Emoción detectada: "
                f"{emotion_info.get('label', 'desconocida')} | "
                f"score={float(emotion_info.get('score', 0.0)):.2f}"
            )
            intent_info = payload.get("intent", {})
            self._append_log(
                "Intención detectada: "
                f"{intent_info.get('intent_name', 'desconocida')} | "
                f"confianza={intent_info.get('confidence', 0.0):.3f} | "
                f"pilar={intent_info.get('pilar', 'general')} | "
                f"respuesta={intent_info.get('response', '')}"
            )
            # Show new vocabulary words if any
            new_words = payload.get("new_words", [])
            if new_words:
                self._append_log(f"📚 Palabras nuevas: {', '.join(new_words)}")
            # Show crisis flag
            if intent_info.get("is_crisis"):
                self._append_log("⚠️ CRISIS EMOCIONAL DETECTADA — Protocolo de contención activado")
            # TTS is now handled directly by AudioWorker (speak_and_wait)
            # to ensure exclusive CPU usage during response processing.

    def _poll_queues(self) -> None:
        try:
            while True:
                message = self.message_queue.get_nowait()
                try:
                    self._handle_worker_message(message)
                finally:
                    self.message_queue_semaphore.release()
        except queue.Empty:
            pass

        try:
            while True:
                frame = self.frame_queue.get_nowait()
                try:
                    self._render_frame(frame)
                finally:
                    self.frame_queue_semaphore.release()
        except queue.Empty:
            pass

        self.after(30, self._poll_queues)

    def _check_routines(self) -> None:
        """Periodic check for routine reminders (#EPIC-007)."""
        if self.routine_scheduler is not None and self.speech_worker is not None:
            try:
                messages = self.routine_scheduler.check_pending()
                for msg in messages:
                    self._append_log(f"🔔 Rutina: {msg}")
                    self.speech_worker.speak(msg)
            except Exception:
                pass
        self.after(30000, self._check_routines)

    def on_close(self) -> None:
        self.stop_workers()
        self.destroy()


# ═══════════════════════════════════════════════════════════════════════════
# Entrypoint
# ═══════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sistema Edge AI Interactivo — PoC",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Ejecutar en modo debug con panel completo de desarrollo "
             "(video, logs, selectores de hardware). Sin este flag, se "
             "inicia en modo ojos expresivos.",
    )
    args = parser.parse_args()

    if args.debug:
        app = EdgeAiDesktopApp()
    else:
        app = EyeModeApp()

    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()


if __name__ == "__main__":
    main()