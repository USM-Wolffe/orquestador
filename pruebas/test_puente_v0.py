"""Tarea 8.1: regresión del puente v0 (spec compatibilidad-v0, "El puente v0 sigue igual").

`puente.py` no se modifica: se copia byte a byte a una carpeta temporal (trabaja junto a su propio archivo) y se
corre con `--una-vez`. `claude` apunta a un `claude.cmd` que lanza el falso de cc; git es el del PATH, como en el v0.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import unittest

from ayudantes import FALSO, GIT, RAIZ_REPO, PruebaOrq

SESION_FALSA = "0f0e0d0c-0b0a-4000-8000-00000000c0de"


class PruebaPuenteV0(PruebaOrq):
    def setUp(self):
        super().setUp()
        self.v0 = self.tmp / "v0"
        self.v0.mkdir()
        shutil.copy2(RAIZ_REPO / "puente.py", self.v0 / "puente.py")
        repo = self.crear_repo("repo-v0", con_commit=True)
        claude = self.tmp / "bin" / "claude.cmd"
        claude.parent.mkdir()
        claude.write_text(f'@echo off\r\n"{sys.executable}" "{FALSO}" --como cc %*\r\n', encoding="utf-8")
        (self.v0 / "config.json").write_text(json.dumps({
            "claude": str(claude), "repo": str(repo), "permitir": ["Read", "Edit", "Write"],
            "denegar": ["Bash(git push:*)", "Read(~/.ssh/**)"], "timeout_min": 5, "intervalo_segundos": 1}),
            encoding="utf-8")
        self.pendientes = self.v0 / "trabajos" / "pendientes"
        self.pendientes.mkdir(parents=True)
        self.hechos = self.v0 / "trabajos" / "hechos"
        self.ruta_traza = self.tmp / "traza.jsonl"

    def correr_puente(self):
        entorno = {**os.environ, "ORQ_FALSO_TRAZA": str(self.ruta_traza)}
        r = subprocess.run([sys.executable, str(self.v0 / "puente.py"), "--una-vez"], cwd=self.v0, env=entorno,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def test_puente_intacto(self):
        original = (RAIZ_REPO / "puente.py").read_bytes()
        self.assertEqual(hashlib.sha256((self.v0 / "puente.py").read_bytes()).hexdigest(),
                         hashlib.sha256(original).hexdigest())
        r = subprocess.run([GIT, "-C", str(RAIZ_REPO), "diff", "--stat", "HEAD", "--", "puente.py"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            self.skipTest("la copia de las pruebas no está en un repo git")
        self.assertEqual(r.stdout.strip(), "", "puente.py tiene cambios respecto del commit")

    def test_trabajo_v0_con_claude_code_falso(self):
        (self.pendientes / "t1.json").write_text(json.dumps(
            {"id": "t1", "tipo": "cc", "cambio": "login", "prompt": "#guion: ok\nAgrega el saludo."}), encoding="utf-8")
        self.correr_puente()
        self.assertEqual((self.hechos / "t1.md").read_text(encoding="utf-8"), "Listo: edité app.py y las pruebas pasan.")
        resultado = json.loads((self.hechos / "t1.resultado.json").read_text(encoding="utf-8"))
        self.assertEqual((resultado["codigo"], resultado["session_id"], resultado["total_cost_usd"]),
                         (0, SESION_FALSA, 0.0421))
        self.assertTrue((self.hechos / "t1.trabajo.json").exists())
        self.assertEqual(json.loads((self.v0 / "sesiones.json").read_text(encoding="utf-8")), {"login": SESION_FALSA})
        self.assertTrue((self.v0 / "estado.json").exists())
        self.assertIn("t1: terminado con código 0", (self.v0 / "registro.log").read_text(encoding="utf-8"))
        argv = json.loads(self.ruta_traza.read_text(encoding="utf-8").splitlines()[0])["argv"]
        self.assertEqual(argv[argv.index("--output-format") + 1], "json")
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "dontAsk")
        self.assertNotIn("--resume", argv)

    def test_limite_de_plan_en_v0(self):
        (self.pendientes / "t2.json").write_text(json.dumps(
            {"id": "t2", "tipo": "cc", "cambio": "login", "prompt": "#guion: limite"}), encoding="utf-8")
        antes = dt.datetime.now().astimezone()
        self.correr_puente()
        trabajo = json.loads((self.pendientes / "t2.json").read_text(encoding="utf-8"))
        self.assertEqual(trabajo["reintentos"], 1)
        espera = (dt.datetime.fromisoformat(trabajo["no_antes_de"]) - antes).total_seconds()
        self.assertLess(abs(espera - 1800), 120)
        self.assertFalse((self.hechos / "t2.md").exists())
        self.assertIn("límite de uso del plan", (self.v0 / "registro.log").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
