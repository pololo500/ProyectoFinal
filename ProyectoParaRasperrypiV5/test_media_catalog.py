"""Skills silenciosos de catálogo: libros y canciones en la Pi."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from media_catalog import (
    catalog_followup_prompt,
    choose_song,
    list_song_names,
    list_story_titles,
    resolve_song,
    resolve_story,
)
from story_library import StoryLibrary


class TestStoryCatalog(unittest.TestCase):
    def test_lista_titulos_y_resuelve_sin_inventar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lib = StoryLibrary(Path(tmp))
            lib.save_story("El sapo valiente", "Había un sapo que daba abrazos. " * 20)
            lib.save_story("La luna y el mar", "La luna miraba el mar de noche. " * 20)
            titles = list_story_titles(lib)
            self.assertEqual(titles, ["El sapo valiente", "La luna y el mar"])
            rec = resolve_story(lib, "sapo")
            assert rec is not None
            self.assertEqual(rec.title, "El sapo valiente")
            self.assertIsNone(resolve_story(lib, "dragón espacial"))

    def test_list_stories_arma_prompt_silencioso(self) -> None:
        prompt = catalog_followup_prompt(
            [{"action": "LIST_STORIES", "param": ""}],
            stories=["El sapo valiente"],
            songs=[],
            child_text="Contame un cuento",
        )
        assert prompt is not None
        self.assertIn("El sapo valiente", prompt)
        self.assertIn("Contame un cuento", prompt)
        self.assertIn("no inventes", prompt.lower())
        self.assertIsNone(
            catalog_followup_prompt(
                [{"action": "PLAY_MUSIC", "param": ""}],
                stories=[],
                songs=[],
                child_text="hola",
            )
        )


class TestSongCatalog(unittest.TestCase):
    def test_lista_y_resuelve_canciones(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "cancion_feliz.mp3").write_bytes(b"xx")
            (root / "nana.wav").write_bytes(b"xx")
            (root / "readme.txt").write_text("no")
            names = list_song_names(root)
            self.assertEqual(names, ["cancion feliz", "nana"])
            path = resolve_song(root, "nana")
            assert path is not None
            self.assertEqual(path.name, "nana.wav")
            self.assertIsNone(resolve_song(root, "reggaeton"))

    def test_resuelve_keane_aunque_el_archivo_tenga_signos_mas(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "harry+potter+musica.mp3").write_bytes(b"xx")
            (root / "Keane+-+Somewhere+Only+We+Know.mp3").write_bytes(b"yy")
            names = list_song_names(root)
            self.assertIn("Keane - Somewhere Only We Know", names)
            path = resolve_song(root, "Keane - Somewhere Only We Know")
            assert path is not None
            self.assertEqual(path.name, "Keane+-+Somewhere+Only+We+Know.mp3")
            by_artist = resolve_song(root, "keane")
            assert by_artist is not None
            self.assertEqual(by_artist.name, "Keane+-+Somewhere+Only+We+Know.mp3")

    def test_con_nombre_pedido_no_elige_otra_cancion_al_azar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "harry+potter+musica.mp3").write_bytes(b"xx")
            self.assertIsNone(choose_song(root, "Keane - Somewhere Only We Know"))
            random_pick = choose_song(root, "")
            assert random_pick is not None
            self.assertEqual(random_pick.name, "harry+potter+musica.mp3")


if __name__ == "__main__":
    unittest.main()
