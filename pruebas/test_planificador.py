"""Tarea 5.2: bucle del planificador (spec planificacion-ejecucion): límites, dependencias, un cambio a la vez,
prioridad y eventos de seguridad de la entrada y de `decisiones\\`."""
from __future__ import annotations

import json
import time
import unittest

from ayudantes import PruebaOrq

from orquestador import estados, registro


class BasePlanificador(PruebaOrq):
    def correr_ciclos(self, orq, segundos: float = 1.5) -> None:
        limite = time.monotonic() + segundos
        while time.monotonic() < limite:
            orq.ciclo()
            time.sleep(0.2)

    def en_curso(self, orq) -> list[str]:
        return [t["id"] for t in orq.proyectos["demo"].registro.lista() if t["estado"] == "en_curso"]

    def agregar_directo(self, orq, estado, **datos):
        ep = orq.proyectos["demo"]
        base = {"titulo": "t", "prompt": "#guion: ok", "agente": "cc", "cambio": "login"}
        t = registro.construir_tarea({**base, **datos}, ep.proyecto, orq.config.agentes, "2026-10-22T10:00:00-03:00")
        t["estado"] = estado
        ep.registro.agregar(t)
        ep.registro.guardar()
        return t


class PruebaLimites(BasePlanificador):
    def test_limite_por_agente(self):
        self.instalar(config={"limites": {"global": 2, "por_agente": {"cc": 1}}})
        orq = self.orquestador()
        self.pedir(orq, {"id": "T-1", "cambio": "a", "prompt": "#guion: colgado"},
                   {"id": "T-2", "cambio": "b", "prompt": "#guion: colgado"})
        self.esperar(orq, self.lanzamientos, mensaje="alguna lanzada")
        self.correr_ciclos(orq)
        self.assertEqual(len(self.en_curso(orq)), 1)
        self.assertEqual(len(self.lanzamientos()), 1)
        self.assertEqual(self.tarea(orq, "T-2")["estado"], "pendiente")

    def test_limite_global(self):
        self.instalar(config={"limites": {"global": 1, "por_agente": {"cc": 2}}})
        orq = self.orquestador()
        self.pedir(orq, {"id": "T-1", "cambio": "a", "prompt": "#guion: colgado"},
                   {"id": "T-2", "cambio": "b", "prompt": "#guion: colgado"})
        self.esperar(orq, self.lanzamientos, mensaje="alguna lanzada")
        self.correr_ciclos(orq)
        self.assertEqual(len(self.en_curso(orq)), 1)
        self.assertEqual(len(self.lanzamientos()), 1)

    def test_cupo_libre_y_cambios_distintos_en_paralelo(self):
        self.instalar(config={"limites": {"global": 2, "por_agente": {"cc": 2}}})
        orq = self.orquestador()
        self.pedir(orq, {"id": "T-1", "cambio": "login", "prompt": "#guion: colgado"},
                   {"id": "T-4", "cambio": "reportes", "prompt": "#guion: colgado"})
        self.esperar(orq, lambda: len(self.lanzamientos()) == 2, mensaje="las dos lanzadas")
        self.assertEqual(len(self.en_curso(orq)), 2)
        self.assertTrue((self.tmp / "wt-login").is_dir())
        self.assertTrue((self.tmp / "wt-reportes").is_dir())

    def test_limite_del_proyecto(self):
        self.instalar(config={"limites": {"global": 3, "por_agente": {"cc": 3}}},
                      proyecto={"limites": {"por_agente": {"cc": 1}}})
        orq = self.orquestador()
        self.pedir(orq, {"id": "T-1", "cambio": "a", "prompt": "#guion: colgado"},
                   {"id": "T-2", "cambio": "b", "prompt": "#guion: colgado"})
        self.esperar(orq, lambda: self.en_curso(orq), mensaje="alguna en curso")
        self.correr_ciclos(orq)
        self.assertEqual(len(self.en_curso(orq)), 1)


class PruebaDependencias(BasePlanificador):
    def test_dependencia_abierta_no_lanza(self):
        self.instalar(config={"limites": {"global": 2, "por_agente": {"cc": 2}}})
        orq = self.orquestador()
        self.pedir(orq, {"id": "T-1", "cambio": "a", "prompt": "#guion: colgado\nmarca-T1"},
                   {"id": "T-2", "cambio": "b", "prompt": "#guion: ok\nmarca-T2", "dependencias": ["T-1"]})
        self.esperar(orq, lambda: self.en_curso(orq) == ["T-1"], mensaje="T-1 en curso")
        self.correr_ciclos(orq)
        self.assertEqual(self.tarea(orq, "T-2")["estado"], "bloqueada")
        self.assertFalse([x for x in self.lanzamientos() if "marca-T2" in x["stdin"]], "T-2 no debió lanzarse")

    def test_se_desbloquea_al_quedar_hecha(self):
        self.instalar()
        orq = self.orquestador()
        self.pedir(orq, {"id": "T-1", "cambio": "a", "prompt": "#guion: ok"},
                   {"id": "T-2", "cambio": "b", "prompt": "#guion: ok", "dependencias": ["T-1"]})
        self.esperar(orq, lambda: self.tarea(orq, "T-2")["estado"] == "hecha", timeout=60, mensaje="T-2 hecha")
        historial = self.tarea(orq, "T-2")["historial"]
        self.assertIn({"de": "bloqueada", "a": "pendiente", "por": "orquestador"},
                      [{k: h[k] for k in ("de", "a", "por")} for h in historial])

    def test_dependencia_fallida(self):
        self.instalar()
        orq = self.orquestador()
        self.agregar_directo(orq, "fallida", id="T-1", cambio="a")
        self.agregar_directo(orq, "bloqueada", id="T-2", cambio="b", dependencias=["T-1"])
        self.correr_ciclos(orq, 0.5)
        t2 = self.tarea(orq, "T-2")
        self.assertEqual(t2["estado"], "bloqueada")
        self.assertEqual(t2["motivo"], "dependencia T-1 fallida")
        self.assertEqual(self.lanzamientos(), [])


class PruebaUnCambioALaVez(BasePlanificador):
    def test_mismo_cambio(self):
        self.instalar(config={"limites": {"global": 2, "por_agente": {"cc": 2}}})
        orq = self.orquestador()
        self.pedir(orq, {"id": "T-1", "cambio": "login", "prompt": "#guion: colgado"},
                   {"id": "T-3", "cambio": "login", "prompt": "#guion: ok"})
        self.esperar(orq, self.lanzamientos, mensaje="una lanzada")
        self.correr_ciclos(orq)
        self.assertEqual(len(self.lanzamientos()), 1)
        self.assertEqual(self.tarea(orq, "T-3")["estado"], "pendiente")

    def test_mismo_cambio_esperando_gate(self):
        self.instalar()
        orq = self.orquestador()
        self.agregar_directo(orq, "esperando_gate", id="T-1")
        self.agregar_directo(orq, "pendiente", id="T-3")
        self.correr_ciclos(orq, 1.0)
        self.assertEqual(self.tarea(orq, "T-3")["estado"], "pendiente")
        self.assertEqual(self.lanzamientos(), [])
        estados.pedir_cancelacion(self.tarea(orq, "T-1"), "sebastian", "cli", "2026-10-22T10:05:00-03:00")
        self.esperar(orq, lambda: self.tarea(orq, "T-3")["estado"] == "hecha", timeout=60, mensaje="T-3 hecha")


class PruebaPrioridad(BasePlanificador):
    def test_menor_prioridad_primero(self):
        self.instalar()
        orq = self.orquestador()
        self.pedir(orq, {"id": "T-baja", "cambio": "a", "prioridad": 200, "prompt": "#guion: colgado\nbaja"},
                   {"id": "T-alta", "cambio": "b", "prioridad": 10, "prompt": "#guion: colgado\nalta"})
        self.esperar(orq, lambda: self.en_curso(orq), mensaje="una en curso")
        self.assertEqual(self.en_curso(orq), ["T-alta"])


class PruebaAgenteNoDisponible(BasePlanificador):
    def test_version_antigua_deja_la_tarea_esperando(self):
        import os
        os.environ["ORQ_FALSO_VERSION"] = "2.1.250 (Claude Code)"
        self.addCleanup(os.environ.pop, "ORQ_FALSO_VERSION", None)
        self.instalar()
        orq = self.orquestador()
        self.pedir(orq, {"id": "T-1", "prompt": "#guion: ok"})
        self.correr_ciclos(orq, 0.6)
        t = self.tarea(orq, "T-1")
        self.assertEqual(t["estado"], "pendiente")
        self.assertIn("agente no disponible", t["motivo"])
        self.assertIn("anterior a la mínima", t["motivo"])
        self.assertEqual(self.lanzamientos(), [])


class PruebaErrores(BasePlanificador):
    def test_error_con_y_sin_intentos_disponibles(self):
        self.instalar()
        orq = self.orquestador()
        self.pedir(orq, {"id": "T-1", "prompt": "#guion: error"})
        self.esperar(orq, lambda: self.tarea(orq, "T-1")["estado"] == "fallida", timeout=90, mensaje="T-1 fallida")
        t = self.tarea(orq, "T-1")
        reintentos = [h for h in t["historial"] if h["a"] == "pendiente" and "se reintenta" in h["motivo"]]
        self.assertEqual(len(reintentos), 2)
        self.assertEqual((t["intentos"], t["max_intentos"], t["motivo"]), (3, 3, "sin intentos: error"))
        self.assertEqual(len(self.lanzamientos()), 3)


class PruebaEventosDeSeguridad(BasePlanificador):
    def eventos(self, orq):
        ruta = orq.proyectos["demo"].proyecto.carpeta_eventos / "eventos.jsonl"
        return [json.loads(x) for x in ruta.read_text(encoding="utf-8").splitlines()] if ruta.exists() else []

    def test_gate_por_archivo_en_decisiones(self):
        self.instalar()
        orq = self.orquestador()
        self.agregar_directo(orq, "esperando_gate", id="T-1")
        carpeta = orq.proyectos["demo"].proyecto.carpeta_decisiones
        (carpeta / "falsa.json").write_text(json.dumps({"op": "aprobar", "id": "T-1"}), encoding="utf-8")
        orq.ciclo()
        seguridad = [e for e in self.eventos(orq) if e["tipo"] == "error" and e["datos"]["clase"] == "seguridad"]
        self.assertEqual(len(seguridad), 1)
        self.assertEqual(seguridad[0]["tarea"], "T-1")
        self.assertIsNone(seguridad[0]["agente"])
        self.assertEqual(self.tarea(orq, "T-1")["estado"], "esperando_gate")

    def test_cowork_pide_aprobar(self):
        self.instalar()
        orq = self.orquestador()
        self.agregar_directo(orq, "esperando_gate", id="T-1")
        entrada = orq.proyectos["demo"].proyecto.carpeta_cowork / "entrada"
        (entrada / "aprobar.json").write_text(json.dumps({"op": "aprobar", "id": "T-1"}), encoding="utf-8")
        orq.ciclo()
        self.assertTrue([e for e in self.eventos(orq) if e["datos"].get("clase") == "seguridad"])




class PruebaUsoPlanGuardado(BasePlanificador):
    def test_uso_plan_queda_en_agentes_json(self):
        self.instalar()
        orq = self.orquestador()
        self.pedir(orq, {"id": "T-1", "prompt": "#guion: uso_plan"})
        self.esperar(orq, lambda: self.tarea(orq, "T-1")["estado"] == "hecha", timeout=60)
        datos = json.loads((self.raiz / "agentes.json").read_text(encoding="utf-8"))
        self.assertEqual(datos["cc"]["uso_plan"]["uso"], 0.62)
        self.assertIsNotNone(datos["cc"]["uso_plan"]["visto_en"])

    def test_sin_uso_plan_queda_null(self):
        self.instalar()
        orq = self.orquestador()
        self.pedir(orq, {"id": "T-1", "prompt": "#guion: ok"})
        self.esperar(orq, lambda: self.tarea(orq, "T-1")["estado"] == "hecha", timeout=60)
        datos = json.loads((self.raiz / "agentes.json").read_text(encoding="utf-8"))
        self.assertIsNone(datos["cc"].get("uso_plan"))


class PruebaCorteOperacion(BasePlanificador):
    def comprobar_corte(self, guion):
        from orquestador import procesos
        self.instalar()
        orq = self.orquestador()
        self.pedir(orq, {"id": "T-1", "prompt": f"#guion: {guion}"})
        self.esperar(orq, lambda: self.tarea(orq, "T-1")["estado"] == "fallida", timeout=20)
        t = self.tarea(orq, "T-1")
        self.assertEqual(t["resultado"]["error"]["clase"], "seguridad")
        self.assertEqual(t["intentos"], 1)
        self.assertEqual(len(t["corridas"]), 1)
        for lanzamiento in self.lanzamientos():
            self.assertFalse(procesos.proceso_vivo(lanzamiento["pid"]))

    def test_conectores_sin_reintento(self):
        self.comprobar_corte("conectores")

    def test_mcp_pendiente_sin_reintento(self):
        self.comprobar_corte("mcp_pendiente")

    def test_herramienta_tarde_sin_reintento(self):
        self.comprobar_corte("herramienta_tarde")

    def test_sin_init_sin_reintento(self):
        self.comprobar_corte("sin_init")


if __name__ == "__main__":
    unittest.main()
