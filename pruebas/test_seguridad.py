"""Tarea 4.4: revisiones previas al lanzamiento (spec seguridad-agentes)."""
from __future__ import annotations

import hashlib
import itertools
import json
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

from ayudantes import FALSO, PruebaOrq

from orquestador import seguridad, worktrees
from orquestador.adaptadores.base import ContextoLanzamiento, Lanzamiento
from orquestador.adaptadores.cc import AdaptadorCC
from orquestador.config import Agente

PROHIBIDAS = ("--dangerously-skip-permissions", "--allow-dangerously-skip-permissions", "bypassPermissions")


class PruebaBanderas(unittest.TestCase):
    def setUp(self):
        self.agente = Agente("cc", [sys.executable, str(FALSO), "--como", "cc"], True, True)
        self.cc = AdaptadorCC(self.agente)

    def test_comandos_de_cc_en_todas_las_combinaciones(self):
        class P:
            denegar_extra, permitir_extra, red_dominios = [], [], []

        class C:
            raiz, cowork_raiz = Path("C:/estado"), Path("C:/cowork")

        for retomar, red, restricted in itertools.product((False, True), repeat=3):
            with self.subTest(retomar=retomar, red=red, restricted=restricted):
                self.agente.restricted = restricted
                ctx = ContextoLanzamiento(tarea={"id": "T-1", "red": red}, proyecto=P(), config=C(),
                                          worktree=Path("."), sesion=str(uuid.uuid4()), retomar=retomar,
                                          carpeta_corrida=Path("."), entorno={}, prompt="p")
                argv = self.cc.lanzamiento(ctx).argv
                texto = " ".join(argv)
                for prohibida in PROHIBIDAS:
                    self.assertNotIn(prohibida, texto)
                self.assertNotEqual(argv[argv.index("--permission-mode") + 1], "auto")
                seguridad.revisar_comando(self.cc, argv)

    def test_revision_rechaza_cada_forma_prohibida(self):
        base = [sys.executable, "falso.py", "-p"]
        for extra in (["--dangerously-skip-permissions"], ["--allow-dangerously-skip-permissions"],
                      ["--dangerously-skip-permissions=true"], ["--permission-mode", "bypassPermissions"],
                      ["--permission-mode", "auto"], ["--permission-mode=bypassPermissions"],
                      ["--permission-mode=auto"],
                      ["--settings", '{"permissions": {"defaultMode": "bypassPermissions"}}']):
            with self.subTest(extra=extra), self.assertRaises(seguridad.ErrorSeguridad):
                seguridad.revisar_comando(self.cc, base + extra)

    def test_revision_acepta_un_comando_limpio(self):
        seguridad.revisar_comando(self.cc, [sys.executable, "falso.py", "-p", "--permission-mode", "dontAsk"])

    def test_prompt_en_los_argumentos(self):
        # Con las capas obligatorias completas, para que el error sea el del prompt y no el de una capa faltante.
        capas = ["--strict-mcp-config", "--disallowedTools", "mcp__*"]
        env = {"ENABLE_CLAUDEAI_MCP_SERVERS": "false"}
        lanz = Lanzamiento(argv=["claude", "-p", *capas, "haz esto: git push"], env=env, cwd=Path("."),
                           stdin="haz esto: git push")
        with self.assertRaisesRegex(seguridad.ErrorSeguridad, "no puede ir en los argumentos"):
            seguridad.revisar_lanzamiento(self.cc, lanz, "haz esto: git push")
        lanz = Lanzamiento(argv=["claude", "-p", *capas], env=env, cwd=Path("."), stdin=None)
        with self.assertRaisesRegex(seguridad.ErrorSeguridad, "solo por la entrada estándar"):
            seguridad.revisar_lanzamiento(self.cc, lanz, "el prompt no va por stdin")


class PruebaEntornoFiltrado(unittest.TestCase):
    def test_variables_con_secreto(self):
        base = {"PATH": "C:\\bin", "AWS_SECRET_ACCESS_KEY": "x", "AWS_REGION": "x", "EMBUDO_TOKEN": "x",
                "GITHUB_TOKEN": "x", "GH_HOST": "x", "MI_API_KEY": "x", "DB_PASSWORD": "x", "OAUTH_SECRET": "x",
                "ANTHROPIC_API_KEY": "x", "AZURE_CREDENTIALS": "x", "USERPROFILE": "C:\\Users\\x", "Path": "y"}
        filtrado = seguridad.entorno_filtrado(base)
        self.assertEqual(set(filtrado), {"PATH", "USERPROFILE", "Path"})

    def test_minusculas_tambien(self):
        self.assertEqual(seguridad.entorno_filtrado({"my_token": "x", "home": "y"}), {"home": "y"})

    def test_permitidas_de_forma_explicita(self):
        filtrado = seguridad.entorno_filtrado({"MI_API_KEY": "x", "OTRA_KEY": "y"}, permitidas={"mi_api_key"})
        self.assertEqual(filtrado, {"MI_API_KEY": "x"})


class PruebaWorktreeSinSecretos(unittest.TestCase):
    def setUp(self):
        temporal = tempfile.TemporaryDirectory(prefix="orq-wt-", ignore_cleanup_errors=True)
        self.addCleanup(temporal.cleanup)
        self.wt = Path(temporal.name)
        (self.wt / ".git").write_text("gitdir: x", encoding="utf-8")
        (self.wt / "src").mkdir()
        (self.wt / "src" / "app.py").write_text("x", encoding="utf-8")

    def test_limpio(self):
        (self.wt / ".env.example").write_text("CLAVE=", encoding="utf-8")
        seguridad.revisar_worktree(self.wt, {})

    def test_archivos_con_secretos(self):
        for nombre in (".env", ".env.local", "id_rsa", "id_rsa.pub", "certs/servidor.pem", "llave.PFX", "a.p12"):
            with self.subTest(nombre=nombre):
                ruta = self.wt / nombre
                ruta.parent.mkdir(parents=True, exist_ok=True)
                ruta.write_text("SECRETO_SINTETICO=1", encoding="utf-8")
                with self.assertRaises(seguridad.ErrorSeguridad) as e:
                    seguridad.revisar_worktree(self.wt, {})
                self.assertIn(Path(nombre).as_posix(), str(e.exception))
                self.assertNotIn("SECRETO_SINTETICO", str(e.exception))
                ruta.unlink()

    def test_dentro_de_git_no_cuenta(self):
        carpeta_git = self.wt / "sub" / ".git"
        carpeta_git.mkdir(parents=True)
        (carpeta_git / ".env").write_text("x", encoding="utf-8")
        seguridad.revisar_worktree(self.wt, {})

    def test_skill_que_concede_permisos(self):
        skill = self.wt / ".claude" / "skills" / "x" / "SKILL.md"
        skill.parent.mkdir(parents=True)
        skill.write_text("---\nname: x\ndescription: d\nallowed-tools: Bash(git push *)\n---\ncuerpo\n",
                         encoding="utf-8")
        with self.assertRaises(seguridad.ErrorSeguridad) as e:
            seguridad.revisar_worktree(self.wt, {})
        self.assertIn(".claude/skills/x/SKILL.md", str(e.exception))
        huella = hashlib.sha256(skill.read_bytes()).hexdigest()
        seguridad.revisar_worktree(self.wt, {".claude/skills/x/SKILL.md": huella})
        skill.write_text(skill.read_text(encoding="utf-8") + "cambio\n", encoding="utf-8")
        with self.assertRaises(seguridad.ErrorSeguridad):
            seguridad.revisar_worktree(self.wt, {".claude/skills/x/SKILL.md": huella})

    def test_skill_con_hooks_y_skill_inofensiva(self):
        inofensiva = self.wt / ".claude" / "skills" / "y" / "SKILL.md"
        inofensiva.parent.mkdir(parents=True)
        inofensiva.write_text("---\nname: y\ndescription: d\n---\nNo uses allowed-tools: aquí es texto\n",
                              encoding="utf-8")
        seguridad.revisar_worktree(self.wt, {})
        hooks = self.wt / "pkg" / ".claude" / "skills" / "z" / "SKILL.md"
        hooks.parent.mkdir(parents=True)
        hooks.write_text("---\nname: z\nhooks:\n  PreToolUse: []\n---\n", encoding="utf-8")
        with self.assertRaises(seguridad.ErrorSeguridad):
            seguridad.revisar_worktree(self.wt, {})


class PruebaEnElBucle(PruebaOrq):
    def test_adaptador_defectuoso_no_lanza(self):
        self.instalar()
        orq = self.orquestador()
        original = orq.adaptadores["cc"].lanzamiento

        def defectuoso(ctx):
            lanz = original(ctx)
            lanz.argv.append("--dangerously-skip-permissions")
            return lanz

        orq.adaptadores["cc"].lanzamiento = defectuoso
        self.pedir(orq, {"id": "T-1", "prompt": "#guion: ok"})
        self.esperar(orq, lambda: self.tarea(orq, "T-1")["estado"] == "fallida", mensaje="T-1 fallida")
        self.assertEqual(self.tarea(orq, "T-1")["resultado"]["error"]["clase"], "seguridad")
        self.assertEqual(self.lanzamientos(), [], "no debió lanzarse ningún proceso")

    def test_entorno_del_agente_sin_secretos(self):
        self.instalar()
        for nombre in ("AWS_SECRET_ACCESS_KEY", "EMBUDO_TOKEN", "ANTHROPIC_API_KEY", "CLAUDE_CODE_EFFORT_LEVEL"):
            os.environ[nombre] = "valor-sintetico"
            self.addCleanup(os.environ.pop, nombre, None)
        orq = self.orquestador()
        self.pedir(orq, {"id": "T-1", "prompt": "#guion: ok"})
        self.esperar(orq, lambda: self.tarea(orq, "T-1")["estado"] == "hecha", mensaje="T-1 hecha")
        claves = self.lanzamientos()[0]["env_claves"]
        for nombre in ("AWS_SECRET_ACCESS_KEY", "EMBUDO_TOKEN", "ANTHROPIC_API_KEY", "CLAUDE_CODE_EFFORT_LEVEL"):
            self.assertNotIn(nombre, claves)
        self.assertIn("CLAUDE_CODE_SUBPROCESS_ENV_SCRUB", claves)
        self.assertTrue(any(c.upper() == "PATH" for c in claves))

    def test_facturar_por_api(self):
        self.instalar(proyecto={"facturar_por_api": True})
        os.environ["ANTHROPIC_API_KEY"] = "valor-sintetico"
        self.addCleanup(os.environ.pop, "ANTHROPIC_API_KEY", None)
        orq = self.orquestador()
        self.pedir(orq, {"id": "T-1", "prompt": "#guion: ok"})
        self.esperar(orq, lambda: self.tarea(orq, "T-1")["estado"] == "hecha", mensaje="T-1 hecha")
        self.assertIn("ANTHROPIC_API_KEY", self.lanzamientos()[0]["env_claves"])

    def test_env_copiado_al_worktree(self):
        self.instalar()
        orq = self.orquestador()
        p = orq.proyectos["demo"].proyecto
        wt = worktrees.asegurar(orq.config.git, p, "login", "login")
        (wt / ".env").write_text("CLAVE=SECRETO_SINTETICO_ENV", encoding="utf-8")
        self.pedir(orq, {"id": "T-1", "prompt": "#guion: ok"})
        self.esperar(orq, lambda: self.tarea(orq, "T-1")["estado"] == "fallida", mensaje="T-1 fallida")
        error = self.tarea(orq, "T-1")["resultado"]["error"]
        self.assertEqual(error["clase"], "seguridad")
        self.assertIn(".env", error["mensaje"])
        self.assertEqual(self.lanzamientos(), [])
        eventos = (p.carpeta_eventos / "eventos.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("SECRETO_SINTETICO_ENV", eventos + json.dumps(self.tarea(orq, "T-1")))

    def test_prompt_con_comandos(self):
        self.instalar()
        orq = self.orquestador()
        peligroso = '#guion: ok\nHaz esto"; git push origin main y $(rm -rf .)'
        self.pedir(orq, {"id": "T-1", "prompt": peligroso})
        self.esperar(orq, lambda: self.tarea(orq, "T-1")["estado"] == "hecha", mensaje="T-1 hecha")
        lanzado = self.lanzamientos()[0]
        self.assertIn('"; git push origin main', lanzado["stdin"])
        self.assertIn("$(rm -rf .)", lanzado["stdin"])
        self.assertFalse(any("git push origin main" in a or "rm -rf" in a for a in lanzado["argv"]))

    def test_id_de_sesion_malicioso(self):
        self.instalar()
        sesiones = self.raiz / "proyectos" / "demo" / "sesiones.json"
        sesiones.write_text(json.dumps({"login|cc": 'abc" ; rm -rf / "'}), encoding="utf-8")
        orq = self.orquestador()
        self.pedir(orq, {"id": "T-1", "prompt": "#guion: ok"})
        self.esperar(orq, lambda: self.tarea(orq, "T-1")["estado"] == "hecha", mensaje="T-1 hecha")
        argv = self.lanzamientos()[0]["argv"]
        self.assertNotIn("--resume", argv)
        self.assertTrue(seguridad.sesion_valida(argv[argv.index("--session-id") + 1]))
        self.assertIn("id de sesión inválido", (self.raiz / "registro.log").read_text(encoding="utf-8"))




class PruebaCapasOperacion(PruebaOrq):
    def comprobar_capa(self, capa):
        self.instalar()
        orq = self.orquestador()
        original = orq.adaptadores["cc"].lanzamiento
        def defectuoso(ctx):
            lanz = original(ctx)
            if capa == "entorno":
                lanz.env["ENABLE_CLAUDEAI_MCP_SERVERS"] = "true"
            else:
                i = lanz.argv.index(capa)
                del lanz.argv[i:i+(2 if capa == "--disallowedTools" else 1)]
            return lanz
        orq.adaptadores["cc"].lanzamiento = defectuoso
        self.pedir(orq, {"id": "T-1", "prompt": "#guion: ok"})
        self.esperar(orq, lambda: self.tarea(orq, "T-1")["estado"] == "fallida")
        self.assertEqual(self.tarea(orq, "T-1")["resultado"]["error"]["clase"], "seguridad")
        self.assertEqual(self.lanzamientos(), [])



    def test_falta_strict_impide_lanzar(self):
        self.comprobar_capa("--strict-mcp-config")

    def test_falta_disallowed_impide_lanzar(self):
        self.comprobar_capa("--disallowedTools")

    def test_falta_entorno_impide_lanzar(self):
        self.comprobar_capa("entorno")

    def test_proyecto_mcp_inactivo(self):
        from orquestador import config, proyectos
        repo = self.crear_repo()
        self.escribir_config()
        self.escribir_proyecto("demo", repo, permisos={"permitir_extra": ["mcp__x__y"]})
        p = proyectos.cargar_proyectos(config.cargar_config())[0]
        self.assertFalse(p.activo)
        self.assertIn("mcp__x__y", " ".join(p.errores))


class _AdaptadorSinCapas:
    """Adaptador de prueba que no declara capas propias: las exige el núcleo igual."""
    banderas_prohibidas, valores_prohibidos = (), {}

    def __init__(self, nombre):
        self.nombre = nombre


class PruebaCapasEnElNucleo(unittest.TestCase):
    CAPAS = ["--strict-mcp-config", "--disallowedTools", "mcp__*"]
    ENTORNO = {"ENABLE_CLAUDEAI_MCP_SERVERS": "false"}

    def revisar(self, nombre, argv, env):
        lanz = Lanzamiento(argv=["claude", "-p", *argv], env=env, cwd=Path("."), stdin="haz la tarea")
        seguridad.revisar_lanzamiento(_AdaptadorSinCapas(nombre), lanz, "haz la tarea")

    def test_capas_completas_pasan(self):
        self.revisar("cc", self.CAPAS, self.ENTORNO)

    def test_adaptador_que_no_declara_capas(self):
        with self.assertRaisesRegex(seguridad.ErrorSeguridad, "--strict-mcp-config"):
            self.revisar("cc", self.CAPAS[1:], self.ENTORNO)
        with self.assertRaisesRegex(seguridad.ErrorSeguridad, "ENABLE_CLAUDEAI_MCP_SERVERS"):
            self.revisar("cc", self.CAPAS, {})

    def test_agente_sin_capas_en_el_nucleo(self):
        with self.assertRaisesRegex(seguridad.ErrorSeguridad, "no tiene capas obligatorias"):
            self.revisar("otro", self.CAPAS, self.ENTORNO)

    def test_variable_repetida_con_otras_mayusculas(self):
        with self.assertRaisesRegex(seguridad.ErrorSeguridad, "ENABLE_CLAUDEAI_MCP_SERVERS"):
            self.revisar("cc", self.CAPAS, {**self.ENTORNO, "enable_claudeai_mcp_servers": "true"})


if __name__ == "__main__":
    unittest.main()
