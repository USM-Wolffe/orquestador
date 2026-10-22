"""Tarea 2.2: `orq tarea reintentar|cancelar` vía `decisiones\\` y rechazo de decisiones de gate por archivo
(spec registro-tareas: "Reintento y cancelación por Sebastian" y "Decisión de gate por archivo")."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

from ayudantes import RAIZ_REPO, PruebaOrq

from orquestador import config as cfg
from orquestador import decisiones, estados, registro
from orquestador import proyectos as proy

MOMENTO = "2026-10-22T10:00:00-03:00"


class BaseDecisiones(PruebaOrq):
    def setUp(self):
        super().setUp()
        self.repo = self.crear_repo()
        self.escribir_config()
        self.escribir_proyecto("demo", self.repo)
        self.config = cfg.cargar_config()
        self.proyecto = proy.cargar_proyectos(self.config)[0]
        self.proyecto.carpeta_decisiones.mkdir(parents=True, exist_ok=True)
        self.reg = registro.Registro(self.proyecto.ruta_tareas)
        self.reg.cargar()
        self.eventos = []

    def agregar(self, id_tarea, estado, **extra):
        t = registro.construir_tarea({"id": id_tarea, "titulo": "t", "prompt": "p", "agente": "cc",
                                      "cambio": "login"}, self.proyecto, self.config.agentes, MOMENTO)
        t.update(estado=estado, **extra)
        self.reg.agregar(t)
        self.reg.guardar()
        return t

    def procesar(self):
        return decisiones.procesar(self.proyecto, self.reg, MOMENTO,
                                   al_evento=lambda tipo, datos, tarea=None: self.eventos.append((tipo, datos, tarea)))

    def releer(self, id_tarea):
        r = registro.Registro(self.proyecto.ruta_tareas)
        r.cargar()
        return r.obtener(id_tarea)


class PruebaPedir(BaseDecisiones):
    def test_reintento_de_tarea_fallida(self):
        self.agregar("T-9", "fallida", intentos=3, max_intentos=3)
        ruta = decisiones.pedir(self.proyecto, "T-9", "reintentar")
        self.assertEqual(ruta.parent, self.proyecto.carpeta_decisiones)
        self.procesar()
        t = self.releer("T-9")
        self.assertEqual((t["estado"], t["max_intentos"]), ("pendiente", 4))
        self.assertEqual(t["historial"][-1]["por"], "sebastian")
        self.assertFalse(list(self.proyecto.carpeta_decisiones.glob("*.json")))
        self.assertTrue(list((self.proyecto.carpeta_decisiones / "procesadas").glob("*.json")))

    def test_cancelar_tarea_que_espera_gate(self):
        self.agregar("T-7", "esperando_gate")
        decisiones.pedir(self.proyecto, "T-7", "cancelar")
        self.procesar()
        self.assertEqual(self.releer("T-7")["estado"], "cancelada")

    def test_cancelar_en_curso_queda_pedida(self):
        self.agregar("T-3", "en_curso")
        decisiones.pedir(self.proyecto, "T-3", "cancelar")
        self.procesar()
        t = self.releer("T-3")
        self.assertEqual(t["estado"], "en_curso")
        self.assertEqual(t["cancelacion"]["por"], "sebastian")

    def test_operacion_invalida_al_pedir(self):
        with self.assertRaises(ValueError):
            decisiones.pedir(self.proyecto, "T-1", "aprobar")
        with self.assertRaises(ValueError):
            decisiones.pedir(self.proyecto, "id con espacio", "cancelar")

    def test_cli_valida_antes_de_escribir(self):
        self.agregar("T-1", "pendiente")
        with self.assertRaises(ValueError):
            decisiones.pedir_desde_cli(self.config, "demo", "T-1", "reintentar")  # no está fallida
        with self.assertRaises(ValueError):
            decisiones.pedir_desde_cli(self.config, "demo", "T-404", "cancelar")
        self.assertFalse(list(self.proyecto.carpeta_decisiones.glob("*.json")))
        texto = decisiones.pedir_desde_cli(self.config, "demo", "T-1", "cancelar")
        self.assertIn("próximo ciclo", texto)
        self.assertEqual(len(list(self.proyecto.carpeta_decisiones.glob("*.json"))), 1)

    def test_cli_orq_tarea(self):
        self.agregar("T-1", "pendiente")
        r = subprocess.run([sys.executable, str(RAIZ_REPO / "orq.py"), "tarea", "demo", "T-1", "cancelar"],
                           capture_output=True, text=True, encoding="utf-8", env=os.environ.copy(), timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(list(self.proyecto.carpeta_decisiones.glob("*.json"))), 1)
        r = subprocess.run([sys.executable, str(RAIZ_REPO / "orq.py"), "tarea", "demo", "T-1", "reintentar"],
                           capture_output=True, text=True, encoding="utf-8", env=os.environ.copy(), timeout=60)
        self.assertEqual(r.returncode, 1)


class PruebaGatePorArchivo(BaseDecisiones):
    def test_decision_de_gate_por_archivo_se_rechaza(self):
        self.agregar("T-7", "esperando_gate")
        for i, solicitud in enumerate([{"op": "aprobar", "id": "T-7"}, {"op": "rechazar", "id": "T-7", "nota": "x"},
                                       {"op": "cancelar", "id": "T-7", "decision": "aprobada"},
                                       {"op": "gate", "id": "T-7"}]):
            (self.proyecto.carpeta_decisiones / f"{i:02d}-falsa.json").write_text(json.dumps(solicitud),
                                                                                 encoding="utf-8")
        resultados = self.procesar()
        self.assertTrue(all(not r["ok"] for r in resultados))
        self.assertEqual(self.releer("T-7")["estado"], "esperando_gate")
        seguridad = [e for e in self.eventos if e[0] == "error" and e[1]["clase"] == "seguridad"]
        self.assertEqual(len(seguridad), 4)

    def test_archivo_ilegible_no_rompe(self):
        (self.proyecto.carpeta_decisiones / "roto.json").write_text("{", encoding="utf-8")
        resultados = self.procesar()
        self.assertFalse(resultados[0]["ok"])

    def test_estados_rechazan_gate_sin_tablero(self):
        t = self.agregar("T-7", "esperando_gate")
        with self.assertRaises(estados.TransicionInvalida):
            estados.decidir_gate(t, "aprobar", "sebastian", "archivo", MOMENTO, huella="h")


if __name__ == "__main__":
    unittest.main()
