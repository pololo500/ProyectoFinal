"""Parseo de /proc para el diagnóstico de CPU por proceso e hilo."""
from __future__ import annotations

import unittest

from diag_cpu import cpu_percent, parse_stat_line, rank_by_cpu


class TestParseStat(unittest.TestCase):
    def test_parsea_comm_con_espacios(self) -> None:
        line = (
            "1234 (Llm Child) R 1 1234 1234 0 0 0 0 0 0 0 "
            "200 50 0 0 20 0 8 0 123 0 4000 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0"
        )
        got = parse_stat_line(line)
        self.assertEqual(got["pid"], 1234)
        self.assertEqual(got["comm"], "Llm Child")
        self.assertEqual(got["utime"], 200)
        self.assertEqual(got["stime"], 50)
        self.assertEqual(got["ticks"], 250)

    def test_cpu_percent_un_nucleo(self) -> None:
        # 50 ticks in 1s at 100 Hz = 50% of one core
        self.assertAlmostEqual(cpu_percent(50, interval_s=1.0, hz=100), 50.0)

    def test_rank_pone_primero_el_mas_pesado(self) -> None:
        rows = [
            {"label": "idle", "cpu": 1.0, "rss_mb": 10},
            {"label": "llama", "cpu": 180.0, "rss_mb": 2000},
            {"label": "vosk", "cpu": 12.0, "rss_mb": 80},
        ]
        ranked = rank_by_cpu(rows)
        self.assertEqual(ranked[0]["label"], "llama")
        self.assertEqual(ranked[1]["label"], "vosk")


if __name__ == "__main__":
    unittest.main()
