"""Tarea 2.3 (operacion-v1): frases en lenguaje simple (design D6, spec tablero)."""
from __future__ import annotations

import datetime as dt
import unittest

from orquestador import frases

AHORA = dt.datetime(2026, 10, 22, 14, 12, tzinfo=dt.timezone(dt.timedelta(hours=-3)))


def ev(tipo, datos=None, ts="2026-10-22T14:00:00-03:00"):
    return {"tipo": tipo, "datos": datos or {}, "ts": ts}


class PruebaFrasesDeEventos(unittest.TestCase):
    def test_frases_comunes(self):
        casos = [
            (ev("inicio"), "Empezó"),
            (ev("inicio", {"retomada": True}), "Retomó su sesión"),
            (ev("herramienta", {"nombre": "leer", "objetivo": "docs/diseno.md", "estado": "ok"}), "Leyó docs/diseno.md"),
            (ev("herramienta", {"nombre": "buscar", "objetivo": "tablero", "estado": "ok"}), "Buscó en el código"),
            (ev("herramienta", {"nombre": "web", "objetivo": "https://x", "estado": "ok"}), "Consultó la web"),
            (ev("herramienta", {"nombre": "skill", "objetivo": "openspec", "estado": "ok"}), "Usó la skill openspec"),
            (ev("herramienta", {"nombre": "tareas", "estado": "ok"}), "Ordenó sus pendientes"),
            (ev("archivo", {"ruta": "orquestador/tablero.py", "accion": "editar"}), "Editó orquestador/tablero.py"),
            (ev("archivo", {"ruta": "nuevo.py", "accion": "escribir"}), "Escribió nuevo.py"),
            (ev("comando", {"comando": "py -3.12 -m unittest", "estado": "ok"}), "Corrió las pruebas"),
            (ev("comando", {"comando": "pytest -q", "estado": "error"}), "Corrió las pruebas: fallaron"),
            (ev("comando", {"comando": "git status", "estado": "ok"}), "Revisó git"),
            (ev("comando", {"comando": "openspec validate x", "estado": "ok"}), "Validó con OpenSpec"),
            (ev("comando", {"comando": "py otra.py", "estado": "ok"}), "Corrió un comando"),
            (ev("fin", {"ok": True}), "Terminó y entregó su informe"),
            (ev("fin", {"ok": False}), "Terminó con error"),
        ]
        for evento, esperada in casos:
            with self.subTest(esperada=esperada):
                self.assertEqual(frases.frase_evento(evento["tipo"], evento["datos"]), esperada)

    def test_mensajes_sin_frase(self):
        self.assertIsNone(frases.frase_evento("mensaje", {"texto": "hola"}))
        self.assertEqual(frases.frases_de_eventos([ev("mensaje", {"texto": "hola"})]), [])

    def test_negado_siempre_visible(self):
        self.assertEqual(frases.frase_evento("comando", {"comando": "git push origin main", "estado": "negado"}),
                         "Intentó git push y se le negó")
        self.assertEqual(frases.frase_evento("herramienta", {"nombre": "leer", "objetivo": "x.py", "estado": "negado"}),
                         "Intentó leer x.py y se le negó")
        bitacora = frases.frases_de_eventos([ev("mensaje", {"texto": "hola"}),
                                             ev("comando", {"comando": "git push origin main", "estado": "negado"})])
        self.assertEqual([b["frase"] for b in bitacora], ["Intentó git push y se le negó"])

    def test_repeticiones_se_juntan(self):
        eventos = [ev("archivo", {"ruta": "orquestador/tablero.py", "accion": "editar"}),
                   ev("archivo", {"ruta": "orquestador/tablero.py", "accion": "editar"})]
        bitacora = frases.frases_de_eventos(eventos)
        self.assertEqual(len(bitacora), 1)
        self.assertEqual(bitacora[0]["frase"], "Editó orquestador/tablero.py (2 veces)")
        eventos.append(ev("archivo", {"ruta": "orquestador/tablero.py", "accion": "editar"}))
        self.assertEqual(frases.frases_de_eventos(eventos)[0]["frase"], "Editó orquestador/tablero.py (3 veces)")

    def test_bitacora_completa_del_escenario(self):
        eventos = [ev("inicio"), ev("herramienta", {"nombre": "leer", "objetivo": "docs/diseno.md", "estado": "ok"}),
                   ev("archivo", {"ruta": "orquestador/tablero.py", "accion": "editar"}),
                   ev("archivo", {"ruta": "orquestador/tablero.py", "accion": "editar"}),
                   ev("comando", {"comando": "py -3.12 -m unittest", "estado": "ok"}), ev("fin", {"ok": True})]
        self.assertEqual([b["frase"] for b in frases.frases_de_eventos(eventos)],
                         ["Empezó", "Leyó docs/diseno.md", "Editó orquestador/tablero.py (2 veces)",
                          "Corrió las pruebas", "Terminó y entregó su informe"])

    def test_gate(self):
        self.assertEqual(frases.frase_evento("gate", {"decision": "aprobada"}), "Aprobaste")
        self.assertEqual(frases.frase_evento("gate", {"decision": "rechazada"}), "Rechazaste con un comentario")


class PruebaFrasesDeError(unittest.TestCase):
    def test_clases(self):
        self.assertEqual(frases.frase_error("seguridad"), "Se detuvo por seguridad")
        self.assertEqual(frases.frase_error("violacion"), "Se detuvo: tocó git")
        self.assertEqual(frases.frase_error("timeout"), "Se le acabó el tiempo")
        self.assertEqual(frases.frase_error("agente"), "Falló el agente")
        self.assertEqual(frases.frase_error("limite_uso", "2026-10-22T15:45:00-03:00"),
                         "Se le acabó el plan; sigue a las 15:45")
        self.assertEqual(frases.frase_evento("error", {"clase": "seguridad"}), "Se detuvo por seguridad")


class PruebaTextoEstacion(unittest.TestCase):
    def tarea(self, estado, **extra):
        return {"id": "T-1", "estado": estado, "agente": "cc", **extra}

    def test_estados_simples(self):
        self.assertEqual(frases.texto_estacion(self.tarea("hecha"), ahora=AHORA), "Hecha por Claude Code")
        self.assertEqual(frases.texto_estacion(self.tarea("esperando_gate"), ahora=AHORA), "Te espera")
        self.assertEqual(frases.texto_estacion(self.tarea("cancelada"), ahora=AHORA), "Cancelada")
        self.assertEqual(frases.texto_estacion(self.tarea("pendiente"), ahora=AHORA), "En cola")

    def test_trabajando_con_minutos(self):
        t = self.tarea("en_curso", iniciada="2026-10-22T14:00:00-03:00")
        self.assertEqual(frases.texto_estacion(t, ahora=AHORA), "Claude Code trabajando hace 12 min")

    def test_bloqueada(self):
        por_id = {"T-2": {"estado": "en_curso"}, "T-9": {"estado": "pendiente"}}
        t = self.tarea("bloqueada", dependencias=["T-2"])
        self.assertEqual(frases.texto_estacion(t, por_id, anterior="T-2", ahora=AHORA), "Espera a la anterior")
        self.assertEqual(frases.texto_estacion(t, por_id, anterior="T-0", ahora=AHORA), "Espera a T-2")

    def test_pendiente_plan_agotado_y_agente_apagado(self):
        agentes = {"cc": {"disponible": True, "agotado_hasta": "2026-10-22T15:45:00-03:00"}}
        self.assertEqual(frases.texto_estacion(self.tarea("pendiente"), ahora=AHORA, agentes=agentes),
                         "Plan agotado · sigue a las 15:45")
        agentes = {"cc": {"disponible": False, "agotado_hasta": None}}
        self.assertEqual(frases.texto_estacion(self.tarea("pendiente"), ahora=AHORA, agentes=agentes),
                         "Agente apagado")

    def test_fallida(self):
        t = self.tarea("fallida", resultado={"error": {"clase": "timeout"}})
        self.assertEqual(frases.texto_estacion(t, ahora=AHORA), "Falló: se le acabó el tiempo")
        t = self.tarea("fallida", resultado={"error": {"clase": "seguridad"}})
        self.assertEqual(frases.texto_estacion(t, ahora=AHORA), "Se detuvo por seguridad")


if __name__ == "__main__":
    unittest.main()
