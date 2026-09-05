"""Smoke test de la ventana tkinter."""
from __future__ import annotations

import unittest


class TestApp(unittest.TestCase):
    def test_ventana_se_construye(self) -> None:
        import app as app_mod

        root = app_mod.App()
        try:
            self.assertEqual(root.title(), "Generador TTS Teo")
            self.assertIn("Elena", root.status.cget("text"))
            self.assertTrue(root.btn.winfo_exists())
            self.assertTrue(root.text.winfo_exists())
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
