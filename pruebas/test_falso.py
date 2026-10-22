"""Tarea 4.1: cada guion del falso de cc produce una salida que el adaptador `cc` lee sin errores."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

from ayudantes import FALSO

from orquestador.adaptadores.base import EstadoLectura
from orquestador.adaptadores.cc import AdaptadorCC
from orquestador.config import Agente

GUIONES_QUE_TERMINAN = ("ok", "lectura", "negado", "limite", "limite_texto", "error", "sin_final",
                        "sesion_inexistente", "intenta_commit")


class PruebaGuiones(unittest.TestCase):
    def setUp(self):
        temporal = tempfile.TemporaryDirectory(prefix="orq-falso-", ignore_cleanup_errors=True)
        self.addCleanup(temporal.cleanup)
        self.cwd = Path(temporal.name)
        self.traza = self.cwd.parent / f"traza-{uuid.uuid4().hex}.jsonl"
        self.addCleanup(lambda: self.traza.unlink(missing_ok=True))
        self.adaptador = AdaptadorCC(Agente("cc", [sys.executable, str(FALSO), "--como", "cc"], True, True))

    def correr_falso(self, guion: str, *extra: str):
        argv = [sys.executable, str(FALSO), "--como", "cc", "-p", "--output-format", "stream-json", "--verbose",
                "--session-id", str(uuid.uuid4()), *extra]
        return subprocess.run(argv, input=f"#guion: {guion}\nhaz algo\n", capture_output=True, text=True,
                              encoding="utf-8", cwd=self.cwd, timeout=60,
                              env={**os.environ, "ORQ_FALSO_TRAZA": str(self.traza)})

    def test_cada_guion_se_lee_sin_errores(self):
        for guion in GUIONES_QUE_TERMINAN:
            with self.subTest(guion=guion):
                r = self.correr_falso(guion)
                lineas = [json.loads(x) for x in r.stdout.splitlines() if x.strip()]
                self.assertTrue(lineas, f"{guion} no emitió nada")
                estado = EstadoLectura(worktree=self.cwd)
                for linea in lineas:
                    self.adaptador.normalizar(linea, estado)
                resultado = self.adaptador.cierre(estado, r.returncode, r.stderr, 1.0)
                self.assertIsNotNone(resultado)
                if guion != "sin_final":
                    self.assertEqual(lineas[0]["type"], "system")
                    self.assertEqual(lineas[0]["subtype"], "init")
                    self.assertEqual(lineas[-1]["type"], "result")

    def test_traza_sin_valores_del_entorno(self):
        os.environ["VARIABLE_SINTETICA_ORQ"] = "valor-que-no-debe-aparecer"
        self.addCleanup(os.environ.pop, "VARIABLE_SINTETICA_ORQ", None)
        self.correr_falso("ok")
        registro = json.loads(self.traza.read_text(encoding="utf-8").splitlines()[0])
        self.assertIn("VARIABLE_SINTETICA_ORQ", registro["env_claves"])
        self.assertNotIn("valor-que-no-debe-aparecer", self.traza.read_text(encoding="utf-8"))
        self.assertEqual(registro["guion"], "ok")
        self.assertEqual(Path(registro["cwd"]).resolve(), self.cwd.resolve())
        self.assertIn("haz algo", registro["stdin"])

    def test_version(self):
        r = subprocess.run([sys.executable, str(FALSO), "--como", "cc", "--version"], capture_output=True,
                           text=True, timeout=30)
        self.assertIn("2.1.306", r.stdout)


if __name__ == "__main__":
    unittest.main()
