"""Tarea 4.5: auditoría de git antes y después de cada corrida y matriz de garantías de cc en `inicio`
(spec seguridad-agentes)."""
from __future__ import annotations

import json
import subprocess
import unittest

from ayudantes import GIT, PruebaOrq

from orquestador import git as gitmod
from orquestador import seguridad, worktrees


class PruebaAuditoriaEnElBucle(PruebaOrq):
    def eventos(self, orq):
        ruta = orq.proyectos["demo"].proyecto.carpeta_eventos / "eventos.jsonl"
        return [json.loads(x) for x in ruta.read_text(encoding="utf-8").splitlines()]

    def test_el_agente_hizo_un_commit(self):
        self.instalar()
        orq = self.orquestador()
        self.pedir(orq, {"id": "T-1", "prompt": "#guion: intenta_commit"})
        self.esperar(orq, lambda: self.tarea(orq, "T-1")["estado"] == "fallida", mensaje="T-1 fallida")
        t = self.tarea(orq, "T-1")
        self.assertEqual(t["resultado"]["error"]["clase"], "violacion")
        violacion = [e for e in self.eventos(orq) if e["tipo"] == "error" and e["datos"]["clase"] == "violacion"]
        self.assertEqual(len(violacion), 1)
        self.assertIn("refs/heads/login", violacion[0]["datos"]["mensaje"])
        # No revierte nada: el commit sigue ahí para que Sebastian lo vea.
        wt = worktrees.ruta_worktree(orq.proyectos["demo"].proyecto, "login")
        log = subprocess.run([GIT, "log", "--oneline", "-1"], cwd=wt, capture_output=True, text=True).stdout
        self.assertIn("commit no autorizado", log)

    def test_corrida_limpia(self):
        self.instalar()
        orq = self.orquestador()
        self.pedir(orq, {"id": "T-1", "prompt": "#guion: ok"})
        self.esperar(orq, lambda: self.tarea(orq, "T-1")["estado"] == "hecha", mensaje="T-1 hecha")
        self.assertFalse([e for e in self.eventos(orq) if e["datos"].get("clase") == "violacion"])

    def test_matriz_en_el_evento_inicio(self):
        self.instalar()
        orq = self.orquestador()
        self.pedir(orq, {"id": "T-1", "prompt": "#guion: ok"})
        self.esperar(orq, lambda: self.tarea(orq, "T-1")["estado"] == "hecha", mensaje="T-1 hecha")
        inicio = next(e for e in self.eventos(orq) if e["tipo"] == "inicio")
        self.assertEqual(inicio["datos"]["niveles"], seguridad.niveles("cc"))

    def test_matriz_de_cc_en_windows(self):
        self.assertEqual(seguridad.niveles("cc", "windows"),
                         {"bypass": "duro", "git": "instruccion", "credenciales": "instruccion",
                          "escritura": "instruccion", "red": "instruccion",
                          "conectores y MCP no declarados": "duro"})


class PruebaFotoDeGit(PruebaOrq):
    def setUp(self):
        super().setUp()
        self.repo = self.crear_repo("repo", con_commit=True)

    def git(self, *args):
        subprocess.run([GIT, *args], cwd=self.repo, check=True, capture_output=True, env=self.entorno_git())

    def foto(self):
        return gitmod.foto(GIT, self.repo, "main")

    def test_sin_cambios(self):
        antes = self.foto()
        (self.repo / "nuevo.txt").write_text("archivo del worktree", encoding="utf-8")
        self.assertEqual(gitmod.diferencias(antes, self.foto()), [])

    def test_cada_cambio_se_nombra(self):
        casos = {
            "commit": (lambda: (self.git("commit", "--allow-empty", "-q", "-m", "x")), "refs/heads/main"),
            "rama nueva": (lambda: self.git("branch", "otra"), "refs/heads/otra"),
            "checkout": (lambda: self.git("checkout", "-q", "-b", "cambiada"), "rama actual (HEAD)"),
            "stash": (lambda: ((self.repo / "README.md").write_text("cambio", encoding="utf-8"),
                               self.git("stash", "-q")), "stash"),
            "config": (lambda: self.git("config", "remote.origin.url", "https://example.invalid/x.git"), ".git/config"),
            "hook": (lambda: (self.repo / ".git" / "hooks" / "pre-push").write_text("exit 0", encoding="utf-8"),
                     ".git/hooks"),
        }
        for nombre, (accion, esperado) in casos.items():
            with self.subTest(caso=nombre):
                antes = self.foto()
                accion()
                self.assertIn(esperado, gitmod.diferencias(antes, self.foto()))

    def test_worktree_que_crea_el_orquestador_en_paralelo(self):
        # Otra corrida del mismo repo crea su worktree y su rama mientras este agente trabaja: no es del agente.
        from orquestador.comun import normalizar

        antes = self.foto()
        self.git("worktree", "add", "-q", "-b", "b", str(self.tmp / "wt-b"), "main")
        propios = frozenset({(normalizar(self.tmp / "wt-b"), "b")})
        self.assertEqual(gitmod.diferencias(antes, self.foto(), propios=propios), [])
        # Sin anotarlo, sí es un cambio; y lo que el agente crea por su cuenta sigue contando aunque haya propios.
        self.assertEqual(gitmod.diferencias(antes, self.foto()), ["lista de worktrees", "refs/heads/b"])
        self.git("branch", "del-agente")
        self.assertEqual(gitmod.diferencias(antes, self.foto(), propios=propios), ["refs/heads/del-agente"])
        # Si el agente quita un worktree propio, cuenta.
        con_b = self.foto()
        self.git("worktree", "remove", "--force", str(self.tmp / "wt-b"))
        self.assertIn("lista de worktrees", gitmod.diferencias(con_b, self.foto(), propios=propios))

    def test_worktree_a_medio_crear(self):
        # `git worktree add` marca el worktree nuevo como "locked initializing" mientras lo crea.
        from orquestador.comun import normalizar

        ruta = str(self.tmp / "wt-b").replace("\\", "/")
        principal = f"worktree {str(self.repo).replace(chr(92), '/')}\nHEAD {'a' * 40}\nbranch refs/heads/main"
        creando = f"{principal}\n\nworktree {ruta}\nHEAD {'a' * 40}\nbranch refs/heads/b\nlocked initializing"
        listo = f"{principal}\n\nworktree {ruta}\nHEAD {'a' * 40}\nbranch refs/heads/b"
        antes, despues = {"worktrees": creando}, {"worktrees": listo}
        self.assertEqual(gitmod.diferencias(antes, despues), ["lista de worktrees"])
        self.assertEqual(gitmod.diferencias(antes, despues, propios={(normalizar(self.tmp / "wt-b"), "b")}), [])

    def test_solo_cuentan_las_creaciones_durante_la_corrida(self):
        repo = self.tmp / "repo-ventana"
        entrada = worktrees._registrar(repo, self.tmp / "wt-x", "x")
        entrada.update(inicio=10.0, fin=12.0)
        self.assertEqual(worktrees.creados_entre(repo, 13.0, 20.0), frozenset())  # rama vieja de otra tarea
        self.assertEqual({r for _, r in worktrees.creados_entre(repo, 11.0, 20.0)}, {"x"})
        self.assertEqual({r for _, r in worktrees.creados_entre(repo, 0.0, 10.5)}, {"x"})
        entrada.update(inicio=30.0, fin=None)  # todavía creándose
        self.assertEqual({r for _, r in worktrees.creados_entre(repo, 40.0, 50.0)}, {"x"})


class PruebaParaleloEnElMismoRepo(PruebaOrq):
    def test_dos_cambios_a_la_vez_terminan_bien(self):
        self.instalar(config={"limites": {"global": 2, "por_agente": {"cc": 2}}},
                      proyecto={"limites": {"por_agente": {"cc": 2}}})
        orq = self.orquestador()
        self.pedir(orq, {"id": "T-1", "cambio": "a", "prompt": "#guion: ok"},
                   {"id": "T-2", "cambio": "b", "prompt": "#guion: ok"})
        self.esperar(orq, lambda: all(self.tarea(orq, i)["estado"] in ("hecha", "fallida") for i in ("T-1", "T-2")),
                     timeout=90, mensaje="T-1 y T-2 terminadas")
        for i in ("T-1", "T-2"):
            self.assertEqual(self.tarea(orq, i)["estado"], "hecha", self.tarea(orq, i)["motivo"])


if __name__ == "__main__":
    unittest.main()
