"""Tareas 5.1 a 5.3 (operacion-v1): detección, `orq instalar` y remoto sin push (design D10–D12)."""
from __future__ import annotations

import builtins
import contextlib
import io
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

from ayudantes import GIT, RAIZ_REPO, PruebaOrq, foto

import orq as cli
from orquestador import instalar


def _bases_tmp(home: Path) -> dict[str, Path]:
    return {
        "USERPROFILE": home,
        "LOCALAPPDATA": home / "AppData" / "Local",
        "APPDATA": home / "AppData" / "Roaming",
        "ProgramFiles": home / "ProgramFiles",
    }


def _tocar(*rutas: Path) -> None:
    for ruta in rutas:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(b"")


class EjecutorFalso:
    """Responde --version y auth/login status sin tocar el disco ni imprimir nada útil al informe."""

    def __init__(self):
        self.versiones: dict[str, str] = {}  # fragmento de ruta → texto de versión
        self.sesiones: dict[str, int] = {}  # fragmento → código de salida de auth/login
        self.llamadas: list[tuple[list[str], bool]] = []
        self.salidas_sesion: list[str] = []

    def __call__(self, comando: list[str], *, leer_salida: bool, entorno: dict, timeout_s: float = 10.0):
        self.llamadas.append((list(comando), leer_salida))
        unidos = " ".join(comando).replace("/", "\\").lower()
        if "auth" in comando or "login" in comando:
            # Sesión: no se lee la salida; si el falso "imprimiera" algo, no debe llegar al informe.
            self.salidas_sesion.append("SECRETO-DE-SESION-NO-DEBE-APARECER")
            codigo = 1
            for clave, valor in self.sesiones.items():
                if clave.lower() in unidos:
                    codigo = valor
                    break
            return codigo, "" if not leer_salida else "SECRETO"
        for clave, texto in self.versiones.items():
            if clave.lower() in unidos:
                return 0, texto if leer_salida else ""
        return 1, ""


class PruebaDeteccion(PruebaOrq):
    def setUp(self):
        super().setUp()
        self.bases = _bases_tmp(self.home)
        self.ejecutor = EjecutorFalso()

    def test_varias_versiones_de_codex_elige_la_mas_alta(self):
        a1 = self.bases["LOCALAPPDATA"] / "OpenAI" / "Codex" / "bin" / "a1" / "codex.exe"
        b2 = self.bases["LOCALAPPDATA"] / "OpenAI" / "Codex" / "bin" / "b2" / "codex.exe"
        _tocar(a1, b2)
        self.ejecutor.versiones = {"a1\\codex.exe": "codex 0.162.0", "b2\\codex.exe": "codex 0.163.0"}
        self.ejecutor.sesiones = {"codex.exe": 0}
        hallazgos = instalar.detectar(self.bases, ejecutar=self.ejecutor)
        codex = next(h for h in hallazgos if h.herramienta == "codex")
        self.assertEqual(codex.version, "0.163.0")
        self.assertTrue(codex.ruta.replace("/", "\\").endswith("b2\\codex.exe"))

    def test_empate_de_version_elige_carpeta_mas_reciente(self):
        vieja = self.bases["LOCALAPPDATA"] / "OpenAI" / "Codex" / "bin" / "vieja" / "codex.exe"
        nueva = self.bases["LOCALAPPDATA"] / "OpenAI" / "Codex" / "bin" / "nueva" / "codex.exe"
        _tocar(vieja, nueva)
        os.utime(vieja.parent, (time.time() - 100, time.time() - 100))
        os.utime(nueva.parent, (time.time(), time.time()))
        self.ejecutor.versiones = {"vieja\\codex.exe": "0.200.0", "nueva\\codex.exe": "0.200.0"}
        self.ejecutor.sesiones = {"codex.exe": 0}
        hallazgos = instalar.detectar(self.bases, ejecutar=self.ejecutor)
        codex = next(h for h in hallazgos if h.herramienta == "codex")
        self.assertTrue(codex.ruta.replace("/", "\\").endswith("nueva\\codex.exe"))

    def test_cursor_por_existencia_sin_ejecutarlo(self):
        cursor = self.bases["LOCALAPPDATA"] / "cursor-agent" / "agent.ps1"
        _tocar(cursor)
        hallazgos = instalar.detectar(self.bases, ejecutar=self.ejecutor)
        h = next(x for x in hallazgos if x.herramienta == "cursor")
        self.assertEqual(h.ruta, str(cursor))
        self.assertIn("E4", h.detalle)
        self.assertFalse(any("agent.ps1" in " ".join(c[0]) for c in self.ejecutor.llamadas))

    def test_git_ausente_queda_en_pendientes(self):
        plan = instalar.planear(False, bases=self.bases, ejecutar=self.ejecutor, raiz=self.raiz,
                                cowork=self.cowork, escritorio=self.tmp / "Desktop", repo=self.tmp / "repo")
        git = next(p for p in plan.pasos if p.nombre == "git")
        self.assertEqual(git.estado, "falta")
        self.assertTrue(any("git" in (x or "").lower() for x in plan.pendientes) or git.pendiente)

    def test_claude_sin_sesion(self):
        claude = self.bases["USERPROFILE"] / ".local" / "bin" / "claude.exe"
        _tocar(claude)
        self.ejecutor.versiones = {"claude.exe": "2.1.306 (Claude Code)"}
        self.ejecutor.sesiones = {"claude.exe": 1}
        plan = instalar.planear(False, bases=self.bases, ejecutar=self.ejecutor, raiz=self.raiz,
                                cowork=self.cowork, escritorio=self.tmp / "Desktop", repo=self.tmp / "repo")
        paso = next(p for p in plan.pasos if p.nombre == "claude")
        self.assertEqual(paso.estado, "revisar")
        self.assertIn("sin sesión", paso.detalle)
        self.assertIn("claude auth login", plan.pendientes)

    def test_sin_leer_credenciales_ni_volcar_salida(self):
        for nombre in (".claude", ".codex", ".cursor", ".ssh"):
            (self.home / nombre).mkdir()
            (self.home / nombre / "credenciales").write_text("SECRETO", encoding="utf-8")
        claude = self.bases["USERPROFILE"] / ".local" / "bin" / "claude.exe"
        _tocar(claude)
        self.ejecutor.versiones = {"claude.exe": "2.1.306"}
        self.ejecutor.sesiones = {"claude.exe": 0}
        abiertos: list[str] = []
        open_real = builtins.open

        def open_spy(file, *args, **kwargs):
            abiertos.append(str(file))
            return open_real(file, *args, **kwargs)

        # pathlib abre con io.open, no con builtins.open: hay que espiar los dos.
        with mock.patch("builtins.open", open_spy), mock.patch("io.open", open_spy):
            plan = instalar.planear(False, bases=self.bases, ejecutar=self.ejecutor, raiz=self.raiz,
                                    cowork=self.cowork, escritorio=self.tmp / "Desktop",
                                    repo=self.tmp / "repo", entorno_base=dict(os.environ))
        texto = instalar.describir(plan, False)
        self.assertTrue(abiertos, "el espía no vio ninguna lectura (ni el ejemplo de config)")
        for prohibido in (".claude", ".codex", ".cursor", ".ssh"):
            self.assertFalse([a for a in abiertos if prohibido in Path(a).parts],
                             f"se abrió algo bajo ~/{prohibido}: {abiertos}")
        self.assertNotIn("SECRETO", texto)
        self.assertTrue(any(not leer for _, leer in self.ejecutor.llamadas if "auth" in " ".join(_)))


    def test_entorno_filtrado_para_cada_ejecucion(self):
        claude = self.bases["USERPROFILE"] / ".local" / "bin" / "claude.exe"
        _tocar(claude)
        self.ejecutor.versiones = {"claude.exe": "2.1.306"}
        entornos = []
        ejecutor = self.ejecutor

        def registrar(comando, *, leer_salida, entorno, timeout_s=10.0):
            entornos.append(entorno)
            return ejecutor(comando, leer_salida=leer_salida, entorno=entorno, timeout_s=timeout_s)

        instalar.detectar(self.bases, ejecutar=registrar,
                          entorno_base={"PATH": "C:\\bin", "GITHUB_TOKEN": "x", "ANTHROPIC_API_KEY": "y"})
        self.assertTrue(entornos)
        for entorno in entornos:
            self.assertNotIn("GITHUB_TOKEN", entorno)
            self.assertNotIn("ANTHROPIC_API_KEY", entorno)


class PruebaEjecucionDeSesion(unittest.TestCase):
    def test_sesion_con_salida_a_devnull(self):
        with mock.patch.object(instalar.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 0)) as run:
            codigo, salida = instalar._ejecutar_default(["claude.exe", "auth", "status"], leer_salida=False,
                                                        entorno={"PATH": "C:\\bin"})
        self.assertEqual((codigo, salida), (0, ""))
        kwargs = run.call_args.kwargs
        for flujo in ("stdin", "stdout", "stderr"):
            self.assertIs(kwargs.get(flujo), subprocess.DEVNULL, flujo)
        self.assertNotIn("capture_output", kwargs)
        self.assertEqual(kwargs["env"], {"PATH": "C:\\bin"})

    def test_agente_que_no_responde_no_rompe_instalar(self):
        for error in (subprocess.TimeoutExpired(["claude.exe"], 10), OSError("no se puede ejecutar")):
            with self.subTest(error=type(error).__name__), mock.patch.object(instalar.subprocess, "run",
                                                                              side_effect=error):
                self.assertEqual(instalar._ejecutar_default(["claude.exe", "auth", "status"], leer_salida=False,
                                                            entorno={}), (-1, ""))


class PruebaInstalarEscrituras(PruebaOrq):
    def setUp(self):
        super().setUp()
        self.bases = _bases_tmp(self.home)
        self.escritorio = self.tmp / "Desktop"
        self.escritorio.mkdir()
        self.repo = self.tmp / "repo-orq"
        self.repo.mkdir()
        (self.repo / "orq.py").write_text("# falso\n", encoding="utf-8")
        self.ejecutor = EjecutorFalso()
        git = self.bases["ProgramFiles"] / "Git" / "cmd" / "git.exe"
        claude = self.bases["USERPROFILE"] / ".local" / "bin" / "claude.exe"
        _tocar(git, claude)
        self.ejecutor.versiones = {"git.exe": "git version 2.45.0", "claude.exe": "2.1.306"}
        self.ejecutor.sesiones = {"claude.exe": 0}
        # Repo git mínimo para el chequeo de pushurl
        if GIT:
            subprocess.run([GIT, "init", "-q", "-b", "main", str(self.repo)], check=True,
                           env=self.entorno_git(), capture_output=True)
            subprocess.run([GIT, "remote", "add", "origin", "https://example.invalid/orq.git"],
                           cwd=self.repo, check=True, env=self.entorno_git(), capture_output=True)

    def _kw(self):
        return dict(bases=self.bases, ejecutar=self.ejecutor, raiz=self.raiz, cowork=self.cowork,
                    escritorio=self.escritorio, repo=self.repo, python_exe=sys.executable)

    def test_simulacion_no_escribe(self):
        antes = foto(self.home, self.escritorio)
        plan = instalar.planear(False, **self._kw())
        self.assertTrue(any(p.estado == "crearía" for p in plan.pasos))
        self.assertEqual(foto(self.home, self.escritorio), antes)

    def test_aplicar_idempotente(self):
        instalar.planear(True, **self._kw())
        cfg = self.raiz / "config.json"
        cmd = self.escritorio / "Orquestador.cmd"
        self.assertTrue(cfg.is_file())
        self.assertTrue(cmd.is_file())
        self.assertTrue(self.cowork.is_dir())
        fechas = {cfg: cfg.stat().st_mtime_ns, cmd: cmd.stat().st_mtime_ns}
        contenidos = {cfg: cfg.read_bytes(), cmd: cmd.read_bytes()}
        plan2 = instalar.planear(True, **self._kw())
        for p in plan2.pasos:
            if p.nombre in ("raiz", "config", "cowork", "acceso-directo"):
                self.assertEqual(p.estado, "ya estaba", p)
        self.assertEqual(cfg.read_bytes(), contenidos[cfg])
        self.assertEqual(cmd.read_bytes(), contenidos[cmd])
        self.assertEqual(cfg.stat().st_mtime_ns, fechas[cfg])
        self.assertEqual(cmd.stat().st_mtime_ns, fechas[cmd])

    def test_config_existente_intacto_con_pendiente(self):
        self.raiz.mkdir(parents=True)
        (self.raiz / "config.json").write_text(json.dumps({
            "limites": {"global": 2, "por_agente": {"cc": 1}},
            "agentes": {"cc": {"ejecutable": "C:\\otra\\claude.exe", "habilitado": True}},
            "herramientas": {"git": "C:\\otra\\git.exe"},
            "tablero": {"puerto": 8765},
            "eventos": {"tope_mb": 10, "rotados": 5},
        }), encoding="utf-8")
        antes = (self.raiz / "config.json").read_bytes()
        plan = instalar.planear(True, **self._kw())
        self.assertEqual((self.raiz / "config.json").read_bytes(), antes)
        self.assertTrue(any("agentes.cc.ejecutable" in p for p in plan.pendientes))

    def test_cmd_ajeno_intacto(self):
        ajeno = self.escritorio / "Orquestador.cmd"
        ajeno.write_text("@echo off\necho ajeno\n", encoding="utf-8")
        plan = instalar.planear(True, **self._kw())
        self.assertEqual(ajeno.read_text(encoding="utf-8"), "@echo off\necho ajeno\n")
        paso = next(p for p in plan.pasos if p.nombre == "acceso-directo")
        self.assertEqual(paso.estado, "revisar")

    def test_pendiente_no_push(self):
        plan = instalar.planear(False, **self._kw())
        self.assertFalse(plan.push_anulado)
        self.assertTrue(any("no-push" in p for p in plan.pendientes))
        self.assertTrue(any("Orquestador-Cowork" in p for p in plan.pendientes))
        self.assertTrue(any("proyecto nuevo" in p for p in plan.pendientes))

    def test_push_anulado_sin_pendiente(self):
        with mock.patch.object(instalar, "pushurl_del_remoto", return_value="no-push"):
            plan = instalar.planear(False, **self._kw())
        self.assertTrue(plan.push_anulado)
        self.assertFalse(any("no-push" in p for p in plan.pendientes))
        paso = next(p for p in plan.pasos if p.nombre == "remoto-push")
        self.assertIn("anulado", paso.detalle)

    def test_aviso_al_arrancar_orq_correr(self):
        if not GIT:
            self.skipTest("git no disponible")
        aviso = instalar.aviso_push(GIT, self.repo)
        self.assertIsNotNone(aviso)
        self.assertIn("no-push", aviso)
        self.assertIn("set-url --push origin no-push", aviso)
        # El planificador emite el aviso al iniciar (junto al de integridad)
        self.instalar()
        with mock.patch("orquestador.instalar.aviso_push", return_value=aviso):
            orq = self.orquestador()
        self.assertTrue(any("no-push" in t for t in self.terminal), self.terminal)


    def test_sin_origin_no_avisa(self):
        if not GIT:
            self.skipTest("git no disponible")
        sin_origin = self.tmp / "repo-sin-origin"
        subprocess.run([GIT, "init", "-q", "-b", "main", str(sin_origin)], check=True, env=self.entorno_git(),
                       capture_output=True)
        self.assertIs(instalar.hay_origin(GIT, sin_origin), False)
        self.assertIsNone(instalar.aviso_push(GIT, sin_origin))
        self.assertIs(instalar.hay_origin(GIT, self.repo), True)
        # git que no se puede ejecutar: no se sabe, y el aviso no se calla (falla segura)
        self.assertIsNone(instalar.hay_origin(str(self.bases["ProgramFiles"] / "Git" / "cmd" / "git.exe"),
                                              self.repo))


class PruebaOrqInstalar(PruebaOrq):
    def test_cli_instalar_simula(self):
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida):
            codigo = cli.main(["instalar"])
        self.assertEqual(codigo, 0)
        self.assertIn("Simulación", salida.getvalue())
        self.assertIn("Pendientes", salida.getvalue())


class PruebaGuiaInstalar(unittest.TestCase):
    def test_guia_al_dia(self):
        ruta = RAIZ_REPO / "docs" / "INSTALAR.md"
        self.assertTrue(ruta.is_file())
        texto = ruta.read_text(encoding="utf-8")
        for tema in ("--aplicar", "no-push", "openspec.cmd", "Get-ExecutionPolicy"):
            self.assertIn(tema, texto)
        leeme = (RAIZ_REPO / "LEEME.md").read_text(encoding="utf-8")
        self.assertIn("docs/INSTALAR.md", leeme)
        parser = cli.construir_parser()
        # Cada `orq …` nombrado en la guía debe existir en el parser
        for m in __import__("re").finditer(r"orq\.py\s+(\S+)", texto):
            sub = m.group(1).strip("`")
            if sub.startswith("-"):
                continue
            self.assertIn(sub, parser._subparsers._group_actions[0].choices, f"falta subcomando {sub}")


if __name__ == "__main__":
    unittest.main()
