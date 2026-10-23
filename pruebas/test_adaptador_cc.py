"""Tarea 4.3: adaptador `cc` (specs adaptadores-agente y eventos-actividad "Normalización de Claude Code")."""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import unittest
import uuid

from ayudantes import FALSO, PruebaOrq

from orquestador import config as cfg
from orquestador import proyectos as proy
from orquestador import seguridad
from orquestador.adaptadores.base import ContextoLanzamiento, EstadoLectura, verificar_version
from orquestador.adaptadores.cc import AdaptadorCC, regla_ruta
from orquestador.corrida import OpcionesCorrida, correr
from orquestador.eventos import EscritorEventos


class BaseCC(PruebaOrq):
    def setUp(self):
        super().setUp()
        repo = self.crear_repo()
        self.escribir_config(agentes={"cc": {"ejecutable": [sys.executable, str(FALSO), "--como", "cc"]}})
        self.escribir_proyecto("demo", repo, red={"permitida": True, "dominios": ["docs.python.org"]})
        self.config = cfg.cargar_config()
        self.proyecto = proy.cargar_proyectos(self.config)[0]
        self.adaptador = AdaptadorCC(self.config.agentes["cc"])
        self.wt = self.tmp / "wt-login"
        self.wt.mkdir()
        self.traza = self.tmp / "traza.jsonl"

    def ctx(self, guion="ok", retomar=False, red=False, sesion=None, entorno=None):
        return ContextoLanzamiento(
            tarea={"id": "T-1", "red": red}, proyecto=self.proyecto, config=self.config, worktree=self.wt,
            sesion=sesion or str(uuid.uuid4()), retomar=retomar, carpeta_corrida=self.tmp / "corridas" / "T-1" / "1",
            entorno=entorno if entorno is not None else {**seguridad.entorno_filtrado(os.environ),
                                                          "ORQ_FALSO_TRAZA": str(self.traza)},
            prompt=f"#guion: {guion}\nTarea sintética\n")

    def correr(self, guion="ok", **kw):
        lanz = self.adaptador.lanzamiento(self.ctx(guion, **kw))
        escritor = EscritorEventos(self.tmp / "eventos", "demo")
        estado = EstadoLectura(worktree=self.wt)
        r = correr(self.adaptador, lanz, estado, escritor, "T-1", 1, OpcionesCorrida(timeout_s=60))
        eventos = [json.loads(x) for x in (self.tmp / "eventos" / "eventos.jsonl").read_text(encoding="utf-8").splitlines()]
        return r, eventos


class PruebaComando(BaseCC):
    def test_comando_de_cc(self):
        ctx = self.ctx()
        lanz = self.adaptador.lanzamiento(ctx)
        argv = lanz.argv
        for bandera in ("-p", "--verbose", "--restricted", "--strict-mcp-config"):
            self.assertIn(bandera, argv)
        self.assertEqual(argv[argv.index("--output-format") + 1], "stream-json")
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "dontAsk")
        self.assertEqual(argv[argv.index("--permission-prompts") + 1], "none")
        self.assertEqual(argv[argv.index("--session-id") + 1], ctx.sesion)
        self.assertNotIn("--resume", argv)
        self.assertEqual(lanz.stdin, ctx.prompt)
        self.assertFalse(any("Tarea sintética" in a for a in argv))
        self.assertEqual(lanz.cwd, self.wt)
        self.assertEqual(argv[:4], [sys.executable, str(FALSO), "--como", "cc"])

    def test_herramientas_sin_y_con_red(self):
        argv = self.adaptador.lanzamiento(self.ctx()).argv
        herramientas = argv[argv.index("--tools") + 1].split(",")
        self.assertNotIn("WebFetch", herramientas)
        self.assertIn("Skill", herramientas)
        self.assertNotIn("PowerShell", herramientas)
        argv = self.adaptador.lanzamiento(self.ctx(red=True)).argv
        self.assertIn("WebFetch", argv[argv.index("--tools") + 1].split(","))

    def test_perfil(self):
        lanz = self.adaptador.lanzamiento(self.ctx())
        ruta = lanz.argv[lanz.argv.index("--settings") + 1]
        perfil = json.loads(lanz.archivos[self.tmp / "corridas" / "T-1" / "1" / "perfil-cc.json"])
        self.assertTrue(ruta.endswith("perfil-cc.json"))
        permisos = perfil["permissions"]
        self.assertEqual(permisos["defaultMode"], "dontAsk")
        self.assertEqual(permisos["disableBypassPermissionsMode"], "disable")
        self.assertTrue(perfil["disableAllHooks"])
        for regla in ("Bash(git commit *)", "PowerShell(git push *)", "Bash(git -C *)", "Bash(git checkout)",
                      "Bash(curl *)", "PowerShell(Invoke-WebRequest *)", "Read(~/.ssh/**)", "Read(~/.embudo/**)",
                      "Read(//**/.env)", "Edit(//**/.env.*)", "Read(~/.claude/**)", f"Read({regla_ruta(self.raiz)})",
                      f"Edit({regla_ruta(self.cowork)})"):
            self.assertIn(regla, permisos["deny"])
        self.assertIn("Bash(git status)", permisos["allow"])
        self.assertNotIn("WebFetch", permisos["allow"])
        con_red = json.loads(next(iter(self.adaptador.lanzamiento(self.ctx(red=True)).archivos.values())))
        self.assertIn("WebFetch(domain:docs.python.org)", con_red["permissions"]["allow"])
        self.assertNotIn("Bash(curl *)", con_red["permissions"]["deny"])

    def test_regla_de_ruta_absoluta(self):
        from pathlib import Path
        self.assertEqual(regla_ruta(Path("C:/Users/Ana Pérez/.orquestador")), "//c/Users/Ana Pérez/.orquestador/**")

    def test_retomar(self):
        sesion = str(uuid.uuid4())
        argv = self.adaptador.lanzamiento(self.ctx(retomar=True, sesion=sesion)).argv
        self.assertEqual(argv[argv.index("--resume") + 1], sesion)
        self.assertNotIn("--session-id", argv)

    def test_respaldo_sin_restricted(self):
        self.config.agentes["cc"].restricted = False
        argv = self.adaptador.lanzamiento(self.ctx()).argv
        self.assertNotIn("--restricted", argv)
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "user")

    def test_entorno_propio_de_cc(self):
        entorno = {"PATH": os.environ.get("PATH", ""), "CLAUDE_CODE_EFFORT_LEVEL": "max"}
        env = self.adaptador.lanzamiento(self.ctx(entorno=entorno)).env
        self.assertNotIn("CLAUDE_CODE_EFFORT_LEVEL", env)
        self.assertEqual(env["CLAUDE_CODE_SUBPROCESS_ENV_SCRUB"], "1")
        self.assertEqual(env["DISABLE_AUTOUPDATER"], "1")


class PruebaNormalizacion(BaseCC):
    def test_corrida_tipica(self):
        r, eventos = self.correr("ok")
        secuencia = [(e["tipo"], e["datos"].get("estado")) for e in eventos]
        self.assertEqual(secuencia, [("inicio", None), ("archivo", None), ("comando", "en_curso"), ("comando", "ok"),
                                     ("mensaje", None), ("fin", None)])
        self.assertEqual(eventos[1]["datos"], {"ruta": "app.py", "accion": "editar"})
        self.assertEqual(eventos[-1]["datos"]["eventos_ignorados"], 1)
        self.assertTrue(r.ok)
        self.assertEqual(r.texto, "Listo: edité app.py y las pruebas pasan.")

    def test_lectura_sin_contenido(self):
        r, eventos = self.correr("lectura")
        herramienta = next(e for e in eventos if e["tipo"] == "herramienta")
        self.assertEqual(herramienta["datos"], {"nombre": "leer", "objetivo": "datos/clientes.csv", "estado": "ok"})
        self.assertNotIn("Cliente", (self.tmp / "eventos" / "eventos.jsonl").read_text(encoding="utf-8"))

    def test_negacion_de_permiso(self):
        r, eventos = self.correr("negado")
        negado = [e for e in eventos if e["datos"].get("estado") == "negado"]
        self.assertEqual(negado[0]["tipo"], "comando")
        self.assertEqual(negado[0]["datos"]["comando"], "git push origin main")
        self.assertEqual(len(r.negaciones), 1)

    def test_consumo(self):
        r, _ = self.correr("ok")
        self.assertEqual((r.consumo["tokens_entrada"], r.consumo["tokens_salida"], r.consumo["tokens_cache_lectura"],
                          r.consumo["tokens_cache_escritura"]), (1200, 340, 800, 50))
        self.assertEqual(r.consumo["costo_usd"], 0.0421)
        self.assertTrue(r.consumo["costo_estimado"])

    def test_termina_sin_evento_final(self):
        r, eventos = self.correr("sin_final")
        self.assertFalse(r.ok)
        self.assertEqual(r.error["clase"], "agente")
        self.assertIn("[REDACTADO]", r.error["mensaje"])
        self.assertNotIn("SECRETOSINTETICO", r.error["mensaje"])
        self.assertEqual(eventos[-1]["tipo"], "fin")


class PruebaLimite(BaseCC):
    def test_limite_con_hora(self):
        antes = dt.datetime.now().astimezone()
        r, eventos = self.correr("limite")
        self.assertIsNotNone(r.limite)
        hasta = dt.datetime.fromisoformat(r.limite.hasta)
        self.assertLess(abs((hasta - antes).total_seconds() - 3600), 120)
        self.assertEqual(r.error["clase"], "limite_uso")
        self.assertIn(("error", "limite_uso"), [(e["tipo"], e["datos"].get("clase")) for e in eventos])

    def test_limite_solo_por_texto(self):
        fijo = dt.datetime(2026, 10, 22, 10, 0, tzinfo=dt.timezone(dt.timedelta(hours=-3)))
        self.adaptador.reloj = lambda: fijo
        r, _ = self.correr("limite_texto")
        self.assertEqual(r.limite.hasta, "2026-10-22T15:45:00-03:00")

    def test_hora_pasada_es_de_manana(self):
        fijo = dt.datetime(2026, 10, 22, 20, 0, tzinfo=dt.timezone(dt.timedelta(hours=-3)))
        self.adaptador.reloj = lambda: fijo
        r, _ = self.correr("limite_texto")
        self.assertEqual(r.limite.hasta, "2026-10-23T15:45:00-03:00")


class PruebaVersion(BaseCC):
    def version(self, texto):
        entorno = {**os.environ, "ORQ_FALSO_VERSION": texto}
        return verificar_version(self.adaptador, self.config.agentes["cc"].ejecutable, entorno)

    def test_version_antigua(self):
        info = self.version("2.1.250 (Claude Code)")
        self.assertFalse(info["disponible"])
        self.assertIn("anterior a la mínima 2.1.302", info["motivo"])

    def test_version_verificada(self):
        info = self.version("2.1.306 (Claude Code)")
        self.assertTrue(info["disponible"])
        self.assertIsNone(info["advertencia"])

    def test_version_mas_nueva(self):
        info = self.version("2.2.0 (Claude Code)")
        self.assertTrue(info["disponible"])
        self.assertIn("versión no verificada", info["advertencia"])

    def test_sin_version(self):
        self.assertFalse(self.version("sin número")["disponible"])




class PruebaConectoresOperacion(BaseCC):
    def test_capas_con_variable_heredada_y_respaldo(self):
        for restricted in (True, False):
            with self.subTest(restricted=restricted):
                self.adaptador.agente.restricted = restricted
                lanz = self.adaptador.lanzamiento(self.ctx(entorno={"ENABLE_CLAUDEAI_MCP_SERVERS": "true"}))
                self.assertEqual(lanz.env["ENABLE_CLAUDEAI_MCP_SERVERS"], "false")
                self.assertEqual(lanz.argv[lanz.argv.index("--disallowedTools")+1], "mcp__*")
                perfil = json.loads(next(iter(lanz.archivos.values())))
                self.assertTrue(perfil["disableClaudeAiConnectors"])
                self.assertIn("mcp__*", perfil["permissions"]["deny"])
                from orquestador.adaptadores.cc import HERRAMIENTAS_TOLERADAS
                pedidas = set(lanz.argv[lanz.argv.index("--tools")+1].split(","))
                self.assertEqual(set(lanz.herramientas_esperadas), pedidas | set(HERRAMIENTAS_TOLERADAS))

    def test_inicio_listas_y_omitidas(self):
        estado = EstadoLectura(worktree=self.wt)
        for cantidad in (2, 60):
            tools = [f"Herramienta{i}" for i in range(cantidad)]
            datos = self.adaptador.normalizar({"type": "system", "subtype": "init", "tools": tools,
                                               "mcp_servers": [{"name": "sintetico", "status": "pending"}]}, estado)[0][1]
            self.assertEqual(datos["herramientas"], tools[:40])
            self.assertEqual(datos["herramientas_omitidas"], max(0, cantidad-40))
            self.assertEqual(datos["mcp"], ["sintetico"])

    def test_inicio_sin_listas(self):
        for extra in ({}, {"tools": [], "mcp_servers": None}, {"tools": "Read", "mcp_servers": []}):
            datos = self.adaptador.normalizar({"type": "system", "subtype": "init", **extra},
                                             EstadoLectura(worktree=self.wt))[0][1]
            self.assertIsNone(datos["herramientas"])

    def test_toleradas_vacias_y_sin_mcp(self):
        from orquestador.adaptadores.cc import HERRAMIENTAS_TOLERADAS
        # Sin exigir que esté vacía: Sebastian la llena en la tarea 1.5.
        for nombre, evidencia in HERRAMIENTAS_TOLERADAS.items():
            self.assertFalse(nombre.startswith("mcp__"))
            self.assertIn("version", evidencia)
            self.assertIn("fecha", evidencia)

    def test_inicio_limpio_guarda_listas_y_matriz(self):
        lanz = self.adaptador.lanzamiento(self.ctx())
        escritor = EscritorEventos(self.tmp / "eventos", "demo")
        r = correr(self.adaptador, lanz, EstadoLectura(worktree=self.wt), escritor, "T-1", 1,
                   OpcionesCorrida(timeout_s=10, niveles=seguridad.niveles("cc")))
        self.assertTrue(r.ok, r.error)
        evento = next(json.loads(x) for x in escritor.archivo.read_text(encoding="utf-8").splitlines()
                      if json.loads(x)["tipo"] == "inicio")
        self.assertEqual(evento["datos"]["herramientas"], lanz.argv[lanz.argv.index("--tools")+1].split(","))
        self.assertEqual(evento["datos"]["mcp"], [])
        self.assertEqual(evento["datos"]["niveles"]["conectores y MCP no declarados"], "duro")


class PruebaUsoPlan(BaseCC):
    def test_guion_uso_plan_en_resultado(self):
        r, _ = self.correr("uso_plan")
        self.assertTrue(r.ok, r.error)
        self.assertEqual(r.uso_plan["uso"], 0.62)
        self.assertIsNotNone(r.uso_plan["visto_en"])
        self.assertIsNotNone(r.uso_plan["reinicia"])

    def test_sin_eventos_queda_null(self):
        r, _ = self.correr("ok")
        self.assertIsNone(r.uso_plan)

    def test_escala(self):
        for valor, esperado in ((62, 0.62), (0.62, 0.62), (0, 0.0), (100, 1.0), (250, None), (-1, None)):
            with self.subTest(valor=valor):
                estado = EstadoLectura(worktree=self.wt)
                self.adaptador.normalizar({"type": "rate_limit_event",
                                           "rate_limit_info": {"status": "allowed_warning", "utilization": valor,
                                                               "resetsAt": 1893456000}}, estado)
                self.assertEqual(estado.uso_plan["uso"], esperado)
                r = self.adaptador.cierre(estado, 0, "", 1.0)
                # sin resultado del agente, uso_plan igual viaja en el cierre si hubo evento
                self.assertEqual(r.uso_plan["uso"], esperado)


if __name__ == "__main__":
    unittest.main()
