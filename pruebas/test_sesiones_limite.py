"""Tarea 5.3: sesiones por (cambio, agente), límite del plan, diff stat con archivos nuevos y huella del estado
(specs planificacion-ejecucion, tablero "Diff stat calculado por el orquestador" y aprobacion-gates)."""
from __future__ import annotations

import datetime as dt
import json
import unittest
import uuid

from ayudantes import PruebaOrq

from orquestador import git as gitmod
from orquestador import registro, worktrees


class BaseSesiones(PruebaOrq):
    def sesiones(self):
        return json.loads((self.raiz / "proyectos" / "demo" / "sesiones.json").read_text(encoding="utf-8"))

    @staticmethod
    def valor(argv, bandera):
        return argv[argv.index(bandera) + 1] if bandera in argv else None

    def agregar_directo(self, orq, **datos):
        ep = orq.proyectos["demo"]
        base = {"titulo": "t", "prompt": "#guion: ok", "agente": "cc", "cambio": "login"}
        extra = {k: datos.pop(k) for k in list(datos) if k in registro.CAMPOS_INTERNOS}
        t = registro.construir_tarea({**base, **datos}, ep.proyecto, orq.config.agentes, "2026-10-22T10:00:00-03:00")
        t.update(estado="pendiente", **extra)
        ep.registro.agregar(t)
        ep.registro.guardar()
        return t


class PruebaSesiones(BaseSesiones):
    def test_se_guarda_antes_de_lanzar_y_se_retoma(self):
        self.instalar()
        orq = self.orquestador()
        self.pedir(orq, {"id": "T-1", "prompt": "#guion: ok"})
        self.esperar(orq, lambda: self.tarea(orq, "T-1")["estado"] == "hecha", mensaje="T-1 hecha")
        primero = self.lanzamientos()[0]["argv"]
        sesion = self.valor(primero, "--session-id")
        self.assertEqual(self.sesiones()["login|cc"], sesion)
        self.pedir(orq, {"id": "T-2", "prompt": "#guion: ok"})
        self.esperar(orq, lambda: self.tarea(orq, "T-2")["estado"] == "hecha", mensaje="T-2 hecha")
        segundo = self.lanzamientos()[1]["argv"]
        self.assertEqual(self.valor(segundo, "--resume"), sesion)
        self.assertNotIn("--session-id", segundo)

    def test_sesion_guardada_mientras_corre(self):
        self.instalar()
        orq = self.orquestador()
        self.pedir(orq, {"id": "T-1", "prompt": "#guion: colgado"})
        self.esperar(orq, lambda: self.lanzamientos(), mensaje="lanzada")
        self.assertEqual(self.sesiones()["login|cc"], self.valor(self.lanzamientos()[0]["argv"], "--session-id"))

    def test_nueva_sesion_pedida(self):
        self.instalar()
        anterior = str(uuid.uuid4())
        (self.raiz / "proyectos" / "demo" / "sesiones.json").write_text(json.dumps({"login|cc": anterior}),
                                                                         encoding="utf-8")
        orq = self.orquestador()
        self.pedir(orq, {"id": "T-2", "prompt": "#guion: ok", "nueva_sesion": True})
        self.esperar(orq, lambda: self.tarea(orq, "T-2")["estado"] == "hecha", mensaje="T-2 hecha")
        argv = self.lanzamientos()[0]["argv"]
        nueva = self.valor(argv, "--session-id")
        self.assertNotEqual(nueva, anterior)
        self.assertEqual(self.sesiones()["login|cc"], nueva)

    def test_sesion_que_ya_no_existe(self):
        self.instalar()
        vieja = str(uuid.uuid4())
        (self.raiz / "proyectos" / "demo" / "sesiones.json").write_text(json.dumps({"login|cc": vieja}),
                                                                         encoding="utf-8")
        orq = self.orquestador()
        self.pedir(orq, {"id": "T-1", "prompt": "#guion: sesion_inexistente"})
        self.esperar(orq, lambda: self.tarea(orq, "T-1")["estado"] == "hecha", mensaje="T-1 hecha")
        primero, segundo = (x["argv"] for x in self.lanzamientos())
        self.assertEqual(self.valor(primero, "--resume"), vieja)
        nueva = self.valor(segundo, "--session-id")
        self.assertTrue(nueva and nueva != vieja)
        self.assertEqual(self.sesiones()["login|cc"], nueva)
        self.assertTrue(any("ya no existía" in h["motivo"] for h in self.tarea(orq, "T-1")["historial"]))


class PruebaLimiteDelPlan(BaseSesiones):
    def test_plan_agotado(self):
        self.instalar(config={"limites": {"global": 2, "por_agente": {"cc": 2}}})
        orq = self.orquestador()
        antes = dt.datetime.now().astimezone()
        self.pedir(orq, {"id": "T-1", "cambio": "a", "prompt": "#guion: limite"})
        self.esperar(orq, lambda: self.tarea(orq, "T-1")["limites_plan"] == 1, mensaje="límite registrado")
        t = self.tarea(orq, "T-1")
        self.assertEqual((t["estado"], t["intentos"]), ("pendiente", 0))
        hasta = dt.datetime.fromisoformat(t["no_antes_de"])
        self.assertLess(abs((hasta - antes).total_seconds() - 3600), 120)
        agentes = json.loads((self.raiz / "agentes.json").read_text(encoding="utf-8"))
        self.assertEqual(agentes["cc"]["agotado_hasta"], t["no_antes_de"])
        self.pedir(orq, {"id": "T-2", "cambio": "b", "prompt": "#guion: ok"})
        orq.ciclo()
        orq.ciclo()
        self.assertEqual(self.tarea(orq, "T-2")["estado"], "pendiente")
        self.assertIn("plan agotado", self.tarea(orq, "T-2")["motivo"])
        self.assertEqual(len(self.lanzamientos()), 1)

    def test_limite_sin_hora_espera_media_hora(self):
        self.instalar()
        orq = self.orquestador()
        antes = dt.datetime.now().astimezone()
        self.pedir(orq, {"id": "T-1", "prompt": "#guion: limite_sin_hora"})
        self.esperar(orq, lambda: self.tarea(orq, "T-1")["limites_plan"] == 1, mensaje="límite registrado")
        t = self.tarea(orq, "T-1")
        self.assertEqual((t["estado"], t["intentos"]), ("pendiente", 0))
        espera = (dt.datetime.fromisoformat(t["no_antes_de"]) - antes).total_seconds()
        self.assertLess(abs(espera - 1800), 60)

    def test_septimo_limite_deja_la_tarea_fallida(self):
        self.instalar()
        orq = self.orquestador()
        self.agregar_directo(orq, id="T-1", prompt="#guion: limite", limites_plan=6)
        self.esperar(orq, lambda: self.tarea(orq, "T-1")["estado"] == "fallida", mensaje="T-1 fallida")
        self.assertEqual(self.tarea(orq, "T-1")["motivo"], "límite de plan repetido")


class PruebaDiffYHuella(BaseSesiones):
    def test_diff_stat_con_archivo_nuevo(self):
        self.instalar()
        orq = self.orquestador()
        self.pedir(orq, {"id": "T-1", "prompt": "#guion: ok"})
        self.esperar(orq, lambda: self.tarea(orq, "T-1")["estado"] == "hecha", mensaje="T-1 hecha")
        datos = json.loads((self.raiz / "proyectos" / "demo" / "diffstat" / "T-1.json").read_text(encoding="utf-8"))
        app = next(a for a in datos["archivos"] if a["ruta"] == "app.py")
        self.assertEqual((app["nuevo"], app["agregadas"]), (True, 1))
        self.assertEqual(datos["base"], "main")

    def test_huella_al_esperar_gate(self):
        self.instalar(proyecto={"gate_por_defecto": True})
        orq = self.orquestador()
        self.pedir(orq, {"id": "T-1", "prompt": "#guion: ok"})
        self.esperar(orq, lambda: self.tarea(orq, "T-1")["estado"] == "esperando_gate", mensaje="esperando gate")
        t = self.tarea(orq, "T-1")
        huella = t["gate"]["huella"]
        self.assertRegex(huella, r"^[0-9a-f]{64}$")
        wt = worktrees.ruta_worktree(orq.proyectos["demo"].proyecto, "login")
        informe = self.raiz / "proyectos" / "demo" / "resultados" / "T-1.md"
        self.assertEqual(gitmod.huella_estado(orq.config.git, wt, "T-1", 1, informe), huella)
        (wt / "app.py").write_text("print('cambiado después de revisar')\n", encoding="utf-8")
        self.assertNotEqual(gitmod.huella_estado(orq.config.git, wt, "T-1", 1, informe), huella)
        (wt / "app.py").write_text("print('hola sintético')\n", encoding="utf-8")
        (wt / "otro.txt").write_text("archivo nuevo sin seguimiento", encoding="utf-8")
        self.assertNotEqual(gitmod.huella_estado(orq.config.git, wt, "T-1", 1, informe), huella)


if __name__ == "__main__":
    unittest.main()
