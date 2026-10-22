"""Tarea 2.2: máquina de estados con actores, historial y estados terminales (spec registro-tareas)."""
from __future__ import annotations

import itertools
import unittest

from orquestador import estados

MOMENTO = "2026-10-22T10:00:00-03:00"
ESTADOS = ("pendiente", "bloqueada", "en_curso", "esperando_gate", "hecha", "fallida", "cancelada")
ACTORES = ("orquestador", "cowork", "sebastian")
VIAS = (None, "entrada", "cli", "tablero", "archivo")

# Tabla esperada, escrita aparte de la implementación: (de, a, actor, via).
ESPERADAS = set()
for de, a in [("bloqueada", "pendiente"), ("pendiente", "bloqueada"), ("pendiente", "en_curso"),
              ("en_curso", "esperando_gate"), ("en_curso", "hecha"), ("en_curso", "pendiente"),
              ("en_curso", "fallida")]:
    ESPERADAS.add((de, a, "orquestador", None))
for de, a in [("esperando_gate", "hecha"), ("esperando_gate", "pendiente")]:
    ESPERADAS.add((de, a, "sebastian", "tablero"))
ESPERADAS.add(("fallida", "pendiente", "cowork", "entrada"))
ESPERADAS.add(("fallida", "pendiente", "sebastian", "cli"))
for de in ("pendiente", "bloqueada", "en_curso", "esperando_gate", "fallida"):
    ESPERADAS.add((de, "cancelada", "cowork", "entrada"))
    ESPERADAS.add((de, "cancelada", "sebastian", "cli"))


def tarea(estado: str, **extra) -> dict:
    t = {"id": "T-1", "estado": estado, "intentos": 0, "max_intentos": 3, "historial": [], "actualizada": None,
         "terminada": None, "gate": {"requiere": True, "decision": None, "nota": None, "en": None, "huella": None,
                                     "via": None}}
    t.update(extra)
    return t


class PruebaTablaDeTransiciones(unittest.TestCase):
    def test_todas_las_combinaciones(self):
        for de, a, actor, via in itertools.product(ESTADOS, ESTADOS, ACTORES, VIAS):
            esperada = (de, a, actor, via) in ESPERADAS
            with self.subTest(de=de, a=a, actor=actor, via=via):
                self.assertEqual(estados.puede(de, a, actor, via), esperada)
                t = tarea(de)
                if esperada:
                    estados.transicion(t, a, actor, "prueba", MOMENTO, via=via)
                    self.assertEqual(t["estado"], a)
                else:
                    with self.assertRaises(estados.TransicionInvalida):
                        estados.transicion(t, a, actor, "prueba", MOMENTO, via=via)
                    self.assertEqual(t["estado"], de)
                    self.assertEqual(t["historial"], [])

    def test_terminales_sin_salida(self):
        for de in ("hecha", "cancelada"):
            for a, actor, via in itertools.product(ESTADOS, ACTORES, VIAS):
                self.assertFalse(estados.puede(de, a, actor, via))


class PruebaHistorial(unittest.TestCase):
    def test_entrada_de_historial(self):
        t = tarea("pendiente")
        estados.transicion(t, "en_curso", "orquestador", "hay cupo", MOMENTO)
        self.assertEqual(t["historial"], [{"de": "pendiente", "a": "en_curso", "por": "orquestador",
                                           "en": MOMENTO, "motivo": "hay cupo"}])
        self.assertEqual(t["actualizada"], MOMENTO)

    def test_crear(self):
        t = tarea(None)
        estados.crear(t, "cowork", MOMENTO, deps_abiertas=[])
        self.assertEqual(t["estado"], "pendiente")
        self.assertEqual(t["historial"][0]["de"], None)
        self.assertEqual(t["historial"][0]["por"], "cowork")
        t2 = tarea(None)
        estados.crear(t2, "cowork", MOMENTO, deps_abiertas=["T-0"])
        self.assertEqual(t2["estado"], "bloqueada")
        self.assertIn("T-0", t2["motivo"])

    def test_terminada_al_llegar_a_terminal(self):
        t = tarea("pendiente")
        estados.transicion(t, "cancelada", "cowork", "ya no hace falta", MOMENTO, via="entrada")
        self.assertEqual(t["terminada"], MOMENTO)


class PruebaOperaciones(unittest.TestCase):
    def test_reintentar_sube_max_intentos(self):
        t = tarea("fallida", intentos=3, max_intentos=3)
        estados.reintentar(t, "sebastian", "cli", MOMENTO)
        self.assertEqual((t["estado"], t["max_intentos"]), ("pendiente", 4))
        self.assertEqual(t["historial"][-1]["por"], "sebastian")

    def test_reintentar_algo_que_no_fallo(self):
        with self.assertRaises(estados.TransicionInvalida):
            estados.reintentar(tarea("hecha"), "cowork", "entrada", MOMENTO)

    def test_cancelar_en_curso_queda_pedida(self):
        t = tarea("en_curso")
        self.assertEqual(estados.pedir_cancelacion(t, "cowork", "entrada", MOMENTO), "pedida")
        self.assertEqual(t["estado"], "en_curso")
        self.assertEqual(t["cancelacion"]["por"], "cowork")
        estados.ejecutar_cancelacion(t, MOMENTO)
        self.assertEqual(t["estado"], "cancelada")
        self.assertEqual(t["historial"][-1]["por"], "cowork")

    def test_cancelar_esperando_gate(self):
        t = tarea("esperando_gate")
        self.assertEqual(estados.pedir_cancelacion(t, "sebastian", "cli", MOMENTO), "cancelada")
        self.assertEqual(t["estado"], "cancelada")

    def test_cancelar_terminal(self):
        with self.assertRaises(estados.TransicionInvalida):
            estados.pedir_cancelacion(tarea("hecha"), "cowork", "entrada", MOMENTO)

    def test_gate_solo_por_tablero(self):
        for via in (None, "cli", "entrada", "archivo"):
            with self.subTest(via=via), self.assertRaises(estados.TransicionInvalida):
                estados.decidir_gate(tarea("esperando_gate"), "aprobar", "sebastian", via, MOMENTO, huella="h")
        for actor in ("cowork", "orquestador"):
            with self.subTest(actor=actor), self.assertRaises(estados.TransicionInvalida):
                estados.decidir_gate(tarea("esperando_gate"), "aprobar", actor, "tablero", MOMENTO, huella="h")

    def test_aprobar_y_rechazar_por_tablero(self):
        t = tarea("esperando_gate")
        estados.decidir_gate(t, "aprobar", "sebastian", "tablero", MOMENTO, huella="abc", sesion="s1")
        self.assertEqual(t["estado"], "hecha")
        self.assertEqual(t["gate"]["decision"], "aprobada")
        self.assertEqual((t["gate"]["via"], t["gate"]["huella"]), ("tablero", "abc"))
        self.assertEqual(t["historial"][-1]["via"], "tablero")
        r = tarea("esperando_gate")
        estados.decidir_gate(r, "rechazar", "sebastian", "tablero", MOMENTO, nota="falta la prueba", huella="x")
        self.assertEqual((r["estado"], r["gate"]["decision"], r["gate"]["nota"]),
                         ("pendiente", "rechazada", "falta la prueba"))

    def test_gate_de_tarea_que_no_espera_gate(self):
        with self.assertRaises(estados.TransicionInvalida):
            estados.decidir_gate(tarea("en_curso"), "aprobar", "sebastian", "tablero", MOMENTO, huella="h")

    def test_rechazo_sin_nota(self):
        with self.assertRaises(estados.TransicionInvalida):
            estados.decidir_gate(tarea("esperando_gate"), "rechazar", "sebastian", "tablero", MOMENTO, huella="h")


if __name__ == "__main__":
    unittest.main()
