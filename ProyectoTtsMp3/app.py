"""Ventana mínima: texto → MP3 con Elena Neural argentina."""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from synthesizer import generate_mp3, prepare_tts_text, suggested_mp3_name


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Generador TTS Teo")
        self.geometry("560x360")
        self.minsize(420, 280)

        ttk.Label(self, text="Texto a decir").pack(anchor="w", padx=12, pady=(12, 4))
        self.text = tk.Text(self, height=10, wrap="word")
        self.text.pack(fill="both", expand=True, padx=12)

        btn_row = ttk.Frame(self)
        btn_row.pack(fill="x", padx=12, pady=8)
        self.btn = ttk.Button(btn_row, text="Generar MP3…", command=self._on_generate)
        self.btn.pack(side="left")

        self.status = ttk.Label(self, text="Voz: es-AR-ElenaNeural (Microsoft)")
        self.status.pack(anchor="w", padx=12, pady=(0, 12))

    def _on_generate(self) -> None:
        raw = self.text.get("1.0", "end")
        if not prepare_tts_text(raw):
            messagebox.showwarning(
                "Texto vacío",
                "Escribí el texto que Teo tiene que decir.",
            )
            return

        dest = filedialog.asksaveasfilename(
            title="Guardar MP3",
            defaultextension=".mp3",
            filetypes=[("MP3", "*.mp3")],
            initialfile=suggested_mp3_name(raw),
        )
        if not dest:
            return

        self.btn.config(state="disabled")
        self.status.config(text="Generando…")
        threading.Thread(
            target=self._run_generate,
            args=(raw, dest),
            daemon=True,
        ).start()

    def _run_generate(self, text: str, dest: str) -> None:
        try:
            path = generate_mp3(text, dest)
        except Exception as exc:
            self.after(0, lambda e=exc: self._finish(None, e))
            return
        self.after(0, lambda p=path: self._finish(p, None))

    def _finish(self, path: object, error: BaseException | None) -> None:
        self.btn.config(state="normal")
        if error is not None:
            self.status.config(text=f"Error: {error}")
            messagebox.showerror("Error al generar MP3", str(error))
            return
        self.status.config(text=f"Guardado: {path}")


def main() -> None:
    App().mainloop()


if __name__ == "__main__":
    main()
