"""Tarea 9.1: ejemplos que cargan con valores seguros, documentación de los comandos y `orq estado` con el falso.
(Que cada comando responde a `--help` está en test_base.PruebaOrqAyuda.test_cada_subcomando_responde_a_help.)"""
from __future__ import annotations

import contextlib
import io
import json
import re
import unittest

from ayudantes import RAIZ_REPO, PruebaOrq, foto

import orq as cli
from orquestador import config as cfg
from orquestador import proyectos as proy


class PruebaEjemplos(PruebaOrq):
    def test_config_de_ejemplo(self):
        ruta = RAIZ_REPO / "ejemplos" / "config.example.json"
        c = cfg.cargar_config(ruta, self.tmp / "raiz")
        self.assertEqual((c.puerto, c.limite_global, c.limite_por_agente), (8765, 2, {"cc": 1}))
        self.assertTrue(c.agentes["cc"].restricted)
        texto = ruta.read_text(encoding="utf-8").lower()
        for prohibido in ("bypass", "dangerously", "api_key", "0.0.0.0"):
            self.assertNotIn(prohibido, texto)

    def test_proyecto_de_ejemplo(self):
        repo = self.crear_repo("repo-demo", con_commit=True)
        self.escribir_config()
        datos = json.loads((RAIZ_REPO / "ejemplos" / "proyecto.example.json").read_text(encoding="utf-8"))
        self.assertLessEqual(set(datos), proy.CLAVES_PROYECTO)
        datos["repo"] = str(repo)
        carpeta = self.raiz / "proyectos" / "demo"
        carpeta.mkdir(parents=True)
        (carpeta / "proyecto.json").write_text(json.dumps(datos), encoding="utf-8")
        p = proy.cargar_proyectos(cfg.cargar_config())[0]
        self.assertEqual(p.errores, [])
        self.assertTrue(p.gate_por_defecto)
        self.assertFalse(p.red_permitida)
        self.assertFalse(p.facturar_por_api)
        self.assertEqual(p.variables_permitidas, [])


class PruebaDocumentacion(unittest.TestCase):
    def test_leeme_documenta_comandos_y_cowork(self):
        texto = (RAIZ_REPO / "LEEME.md").read_text(encoding="utf-8")
        for comando in ("orq.py correr", "orq.py estado", "orq.py tarea", "orq.py proyecto nuevo",
                        "orq.py importar-v0", "orq.py instalar", "--sin-tablero",
                        "--permitir-codigo-modificado", "--aplicar"):
            self.assertIn(comando, texto)
        self.assertIn("docs/INSTALAR.md", texto)
        self.assertIn(r"Orquestador-Cowork\<proyecto>", texto)
        self.assertIn("código de 6 dígitos", texto)
        self.assertIn("py -3.12 puente.py --una-vez", texto)  # la parte del v0 sigue ahí

    def test_verificacion_manual(self):
        texto = (RAIZ_REPO / "docs" / "verificacion-manual.md").read_text(encoding="utf-8")
        for tema in ("--restricted", "--permission-prompts none", "auth status", "--version", "Aprobar",
                     r"Orquestador-Cowork\demo", "openspec.cmd validate operacion-v1 --strict"):
            self.assertIn(tema, texto)
        self.assertIsNone(re.search(r"(?<![\w.\\/-])openspec\s", texto), "usa openspec.cmd, no openspec")


class PruebaOrqEstado(PruebaOrq):
    def test_resumen_con_el_falso(self):
        self.instalar(config={"limites": {"global": 2, "por_agente": {"cc": 2}}})
        orq = self.orquestador()
        self.pedir(orq, {"id": "T-1", "cambio": "a", "prompt": "#guion: ok"},
                   {"id": "T-2", "cambio": "b", "prompt": "#guion: ok", "gate": {"requiere": True},
                    "titulo": "Con gate"},
                   {"id": "T-3", "cambio": "c", "prompt": "#guion: ok", "dependencias": ["T-2"]})
        orq.ciclo()
        acuses = [r.read_text(encoding="utf-8") for r in (self.cowork / "demo" / "respuestas").glob("*.json")]
        self.assertIsNotNone(self.tarea(orq, "T-1"), acuses)
        def como_van():
            return {i: (self.tarea(orq, i)["estado"], self.tarea(orq, i)["motivo"],
                        self.tarea(orq, i)["historial"][-1]["motivo"]) for i in ("T-1", "T-2", "T-3")}

        self.esperar(orq, lambda: self.tarea(orq, "T-1")["estado"] == "hecha"
                     and self.tarea(orq, "T-2")["estado"] == "esperando_gate", timeout=60, mensaje=como_van)
        antes = foto(self.raiz, self.cowork)
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida):
            self.assertEqual(cli.main(["estado"]), 0)
        texto = salida.getvalue()
        self.assertEqual(foto(self.raiz, self.cowork), antes, "orq estado no debe escribir nada")
        self.assertIn("Orquestador: corriendo", texto)
        self.assertIn("Agente cc: disponible (versión 2.1.306)", texto)
        self.assertIn("Proyecto demo: 1 bloqueada · 1 esperando_gate · 1 hecha", texto)
        huella = self.tarea(orq, "T-2")["gate"]["huella"][:12]
        self.assertRegex(texto, rf"T-2\s+esperando_gate\s+b\s+cc\s+Con gate\s+huella {huella}")
        self.assertRegex(texto, r"T-3\s+bloqueada")
        self.assertNotRegex(texto, r"T-1\s+hecha")  # las terminadas solo se cuentan
        self.assertIn("Carpeta de Cowork:", texto)




class PruebaConectoresDocumentados(unittest.TestCase):
    def test_paso_siete_cinco_capas_y_campos(self):
        texto = (RAIZ_REPO / "docs" / "verificacion-manual.md").read_text(encoding="utf-8")
        paso = texto.split("## 7. Conectores de claude.ai", 1)[1]
        for capa in ("ENABLE_CLAUDEAI_MCP_SERVERS", "disableClaudeAiConnectors", "--disallowedTools",
                     "permissions.deny", "--strict-mcp-config", "tools", "mcp_servers", "ConvertFrom-Json",
                     "utilization"):
            self.assertIn(capa, paso)
        for letra in "abcdefgh":
            self.assertIn(f"### ({letra})", paso)
        self.assertIn("openspec.cmd validate operacion-v1 --strict", texto)


if __name__ == "__main__":
    unittest.main()
