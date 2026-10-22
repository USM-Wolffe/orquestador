"""Tarea 5.1: un worktree por cambio (spec planificacion-ejecucion, "Un worktree por cambio")."""
from __future__ import annotations

import subprocess
import threading
import time
import unittest
from pathlib import Path

from ayudantes import GIT, PruebaOrq

from orquestador import config as cfg
from orquestador import git as gitmod
from orquestador import proyectos as proy
from orquestador import worktrees


class PruebaWorktrees(PruebaOrq):
    def setUp(self):
        super().setUp()
        self.repo = self.crear_repo("repo", con_commit=True)
        self.escribir_config()
        self.escribir_proyecto("demo", self.repo)
        self.config = cfg.cargar_config()
        self.proyecto = proy.cargar_proyectos(self.config)[0]

    def salida(self, cwd, *args):
        return subprocess.run([GIT, *args], cwd=cwd, capture_output=True, text=True).stdout.strip()

    def test_worktree_nuevo(self):
        wt = worktrees.asegurar(self.config.git, self.proyecto, "login", "login")
        self.assertEqual(wt, self.tmp / "wt-login")
        self.assertTrue((wt / ".git").is_file())
        self.assertEqual(self.salida(wt, "branch", "--show-current"), "login")
        self.assertEqual(self.salida(wt, "rev-parse", "HEAD"), self.salida(self.repo, "rev-parse", "main"))

    def test_reutiliza_el_existente(self):
        primero = worktrees.asegurar(self.config.git, self.proyecto, "login", "login")
        (primero / "trabajo.txt").write_text("avance", encoding="utf-8")
        segundo = worktrees.asegurar(self.config.git, self.proyecto, "login", "login")
        self.assertEqual(primero, segundo)
        self.assertTrue((segundo / "trabajo.txt").exists())

    def test_rama_existente(self):
        subprocess.run([GIT, "branch", "reportes"], cwd=self.repo, check=True, capture_output=True)
        wt = worktrees.asegurar(self.config.git, self.proyecto, "reportes", "reportes")
        self.assertEqual(self.salida(wt, "branch", "--show-current"), "reportes")

    def test_dos_cambios_nuevos_a_la_vez(self):
        activos, maximo, candado = [0], [0], threading.Lock()

        def ejecutar(git, cwd, *args, **kw):
            with candado:
                activos[0] += 1
                maximo[0] = max(maximo[0], activos[0])
            time.sleep(0.3)
            try:
                return gitmod.correr_git(git, cwd, *args, **kw)
            finally:
                with candado:
                    activos[0] -= 1

        errores = []

        def crear(cambio):
            try:
                worktrees.asegurar(self.config.git, self.proyecto, cambio, cambio, ejecutar=ejecutar)
            except Exception as e:  # noqa: BLE001
                errores.append(e)

        hilos = [threading.Thread(target=crear, args=(c,)) for c in ("login", "reportes")]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join(60)
        self.assertEqual(errores, [])
        self.assertEqual(maximo[0], 1, "los git worktree add del mismo repo deben ir uno después del otro")
        self.assertTrue((self.tmp / "wt-login" / ".git").exists())
        self.assertTrue((self.tmp / "wt-reportes" / ".git").exists())

    def test_carpeta_que_no_es_worktree(self):
        (self.tmp / "wt-login").mkdir()
        with self.assertRaises(worktrees.ErrorWorktree):
            worktrees.asegurar(self.config.git, self.proyecto, "login", "login")

    def test_no_borra_nada(self):
        wt = worktrees.asegurar(self.config.git, self.proyecto, "login", "login")
        worktrees.asegurar(self.config.git, self.proyecto, "login", "login")
        listados = [Path(x[len("worktree "):]).resolve() for x in
                    self.salida(self.repo, "worktree", "list", "--porcelain").splitlines() if x.startswith("worktree ")]
        self.assertIn(wt.resolve(), listados)
        self.assertEqual(len(listados), 2)


if __name__ == "__main__":
    unittest.main()
