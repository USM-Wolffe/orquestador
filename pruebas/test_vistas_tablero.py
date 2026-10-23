"""Tarea 2.4 (operacion-v1): vistas.tablero() (design D4, spec tablero)."""
from __future__ import annotations

import datetime as dt
import unittest

from orquestador import vistas

AHORA = dt.datetime(2026, 10, 22, 14, 12, tzinfo=dt.timezone(dt.timedelta(hours=-3)))


def tarea(id_, **extra):
    base = {"id": id_, "titulo": f"Tarea {id_}", "prompt": "PROMPT-SECRETO-SINTETICO", "agente": "cc",
            "cambio": "etapa-2", "estado": "pendiente", "dependencias": [], "creada": "2026-10-22T10:00:00-03:00",
            "actualizada": "2026-10-22T10:00:00-03:00", "iniciada": None, "terminada": None, "corridas": [],
            "gate": {"requiere": True}, "intentos": 0, "max_intentos": 3}
    base.update(extra)
    return base


def instantanea(tareas, agentes=None):
    return {"momento": "2026-10-22T14:12:00-03:00",
            "agentes": agentes if agentes is not None else {"cc": {"disponible": True, "version": "2.1.306",
                                                                   "agotado_hasta": None}},
            "proyectos": {"demo": {"tareas": tareas}}}


class PruebaTurno(unittest.TestCase):
    def test_gate_con_explicacion_evidencia_y_revision(self):
        revisada = tarea("T-1", estado="hecha", explicacion="Que cc reciba tareas.")
        revision = tarea("T-1r", estado="esperando_gate", revisa="T-1", titulo="Revisión de T-1")
        datos = vistas.tablero(instantanea([revisada, revision]), AHORA, "demo",
                                diffstats={"T-1r": {"total": {"archivos": 6}, "archivos": []}},
                                informes={"T-1r": "Veredicto: sin reparos\nTodo bien, sin observaciones."},
                                eventos={"T-1r": [{"tipo": "comando", "ts": "2026-10-22T14:00:00-03:00",
                                                   "datos": {"comando": "py -3.12 -m unittest", "estado": "ok"}}]})
        self.assertEqual(len(datos["turno"]), 1)
        entrada = datos["turno"][0]
        self.assertEqual(entrada["titulo"], revisada["titulo"])
        self.assertEqual(entrada["explicacion"], "Que cc reciba tareas.")
        self.assertEqual(entrada["archivos"], 6)
        self.assertEqual(entrada["pruebas"], {"ok": True, "en": "2026-10-22T14:00:00-03:00"})
        self.assertEqual(entrada["revision"]["veredicto"], "sin_reparos")
        self.assertIn("Todo bien", entrada["revision"]["resumen"])
        self.assertEqual(entrada["revision"]["agente"], "cc")

    def test_veredicto_con_reparos_y_sin_veredicto(self):
        self.assertEqual(vistas.veredicto_revision("Veredicto: con reparos\nFalta una prueba.")[0], "con_reparos")
        self.assertEqual(vistas.veredicto_revision("Un informe cualquiera\nsin veredicto")[0], "no_concluyente")
        self.assertEqual(vistas.veredicto_revision(None)[0], "no_concluyente")

    def test_sin_prompt_en_la_respuesta(self):
        gate = tarea("T-1", estado="esperando_gate", explicacion="Algo simple.")
        datos = vistas.tablero(instantanea([gate]), AHORA, "demo")
        import json
        self.assertNotIn("PROMPT-SECRETO-SINTETICO", json.dumps(datos, ensure_ascii=False))
        self.assertIsNone(datos["turno"][0]["revision"])


class PruebaAgentesYPlan(unittest.TestCase):
    def test_agente_trabajando_con_frase_y_consumo(self):
        en_curso = tarea("T-1", estado="en_curso", titulo="Adaptador de Codex",
                         iniciada="2026-10-22T14:00:00-03:00",
                         corridas=[{"intento": 1, "agente": "cc", "inicio": "2026-10-22T13:25:00-03:00",
                                     "duracion_s": 2820}])
        agentes = {"cc": {"disponible": True, "agotado_hasta": None,
                          "uso_plan": {"uso": 0.62, "visto_en": "2026-10-22T14:07:00-03:00", "reinicia": None}}}
        datos = vistas.tablero(instantanea([en_curso], agentes), AHORA, "demo",
                                eventos={"T-1": [{"tipo": "archivo", "ts": "2026-10-22T14:11:20-03:00",
                                                  "datos": {"ruta": "adaptadores/codex.py", "accion": "editar"}}]})
        fila = datos["agentes"][0]
        self.assertEqual((fila["nombre"], fila["estado"], fila["tarea"]), ("Claude Code", "trabajando", "Adaptador de Codex"))
        self.assertEqual(fila["frase"], "Editó adaptadores/codex.py")
        self.assertEqual(fila["frase_en"], "2026-10-22T14:11:20-03:00")
        self.assertEqual(fila["hoy"], {"minutos": 47, "tareas": 1})
        self.assertEqual(fila["plan"], {"uso": 0.62, "visto_en": "2026-10-22T14:07:00-03:00"})

    def test_plan_orden_topologico_y_textos(self):
        tareas = [tarea("E2-5", estado="bloqueada", dependencias=["E2-4"]),
                  tarea("E2-4", estado="esperando_gate", dependencias=["E2-3"]),
                  tarea("E2-1", estado="hecha"), tarea("E2-2", estado="hecha", dependencias=["E2-1"]),
                  tarea("E2-3", estado="hecha", dependencias=["E2-2"]),
                  tarea("E2-6", estado="bloqueada", dependencias=["E2-5"])]
        datos = vistas.tablero(instantanea(tareas), AHORA, "demo")
        linea = datos["plan"][0]
        self.assertEqual((linea["listas"], linea["total"]), (3, 6))
        ids = [e["id"] for e in linea["estaciones"]]
        self.assertEqual(ids, ["E2-1", "E2-2", "E2-3", "E2-4", "E2-5", "E2-6"])
        por_id = {e["id"]: e for e in linea["estaciones"]}
        self.assertEqual(por_id["E2-4"]["texto"], "Te espera")
        self.assertEqual(por_id["E2-5"]["texto"], "Espera a la anterior")
        self.assertEqual(por_id["E2-6"]["texto"], "Espera a la anterior")
        self.assertTrue(linea["nota"])

    def test_cambio_viejo_no_aparece(self):
        vieja = tarea("T-9", estado="hecha", cambio="viejo", terminada="2026-10-20T10:00:00-03:00",
                      actualizada="2026-10-20T10:00:00-03:00")
        datos = vistas.tablero(instantanea([vieja]), AHORA, "demo")
        self.assertEqual(datos["plan"], [])


if __name__ == "__main__":
    unittest.main()
