from __future__ import annotations

import json
import queue
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


class EdgeAiDesktopApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Edge AI PoC")
        self.geometry("1280x820")
        self.minsize(1100, 720)

        self.camera_options = discover_cameras()
        self.microphone_options = discover_microphones()
        self.output_device_options = discover_output_devices()

        self.message_queue: queue.Queue[WorkerMessage] = queue.Queue(maxsize=128)
        self.message_queue_semaphore = threading.BoundedSemaphore(128)
        self.frame_queue_semaphore = threading.BoundedSemaphore(2)
        self.frame_queue: queue.Queue[object] = queue.Queue(maxsize=2)
        self.camera_worker: CameraWorker | None = None
        self.audio_worker: AudioWorker | None = None
        self.intent_dispatcher: IntentDispatcher | None = None
        self.speech_worker: SpeechWorker | None = None

        self._current_photo = None
        self._build_ui()
        self._refresh_device_labels()
        self.after(30, self._poll_queues)

    def _build_ui(self) -> None:
        self.configure(bg="#0f172a")

        header = ttk.Frame(self, padding=12)
        header.pack(fill="x")

        title = ttk.Label(header, text="Sistema Edge AI Interactivo - PoC", font=("Segoe UI", 18, "bold"))
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
        self.microphone_combo = ttk.Combobox(controls, textvariable=self.microphone_var, state="readonly", width=56)
        self.microphone_combo.grid(row=1, column=1, sticky="we", pady=4)

        ttk.Label(controls, text="Parlante:").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=4)
        self.output_device_combo = ttk.Combobox(controls, textvariable=self.output_device_var, state="readonly", width=56)
        self.output_device_combo.grid(row=2, column=1, sticky="we", pady=4)

        controls.columnconfigure(1, weight=1)

        actions = ttk.Frame(controls)
        actions.grid(row=0, column=2, rowspan=3, padx=(14, 0), sticky="ns")

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

        self.speech_worker = SpeechWorker(output_device_index=output_device_index)
        self.speech_worker.start()

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
        self.status_var.set("Estado: detenido")
        self._append_log("Workers detenidos correctamente")

    def _append_log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{text}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

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
            self.status_var.set(str(message.payload))
        elif message.kind == "frame":
            self._render_frame(message.payload)
        elif message.kind == "emotion":
            payload = message.payload or {}
            label = payload.get('label')
            score = float(payload.get('score', 0.0))
            self._append_log(
                "Emoción detectada: "
                f"{label or 'desconocida'} "
                f"(score={score:.2f})"
            )
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
                f"respuesta={intent_info.get('response', '')}"
            )
            response_text = str(intent_info.get("response", "")).strip()
            if response_text and self.speech_worker is not None:
                self.speech_worker.speak(response_text)

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

    def on_close(self) -> None:
        self.stop_workers()
        self.destroy()


def main() -> None:
    app = EdgeAiDesktopApp()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()


if __name__ == "__main__":
    main()