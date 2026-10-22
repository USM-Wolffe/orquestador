"""Tarea 5.4: recuperación al reiniciar (spec planificacion-ejecucion, "Recuperación al reiniciar")."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import unittest

from ayudantes import RAIZ_REPO, PruebaOrq

from orquestador import procesos, registro


def esperar_muerto(pid, segundos=15.0):
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if not procesos.proceso_vivo(pid):
            return True
        time.sleep(0.1)
    return False


class BaseReinicio(PruebaOrq):
    def escribir_tareas(self, *tareas):
        """Deja tareas en tareas.json como las dejó una ejecución anterior (antes de arrancar el orquestador)."""
        from orquestador import config as cfg
        from orquestador import proyectos as proy

        config = cfg.cargar_config()
        p = proy.cargar_proyectos(config)[0]
        reg = registro.Registro(p.ruta_tareas)
        reg.cargar()
        for datos in tareas:
            internos = {k: datos.pop(k) for k in list(datos) if k in registro.CAMPOS_INTERNOS}
            t = registro.construir_tarea({"titulo": "t", "prompt": "#guion: ok", "agente": "cc", "cambio": "login",
                                          **datos}, p, config.agentes, "2026-10-22T10:00:00-03:00")
            t.update(internos)
            t["historial"] = t.get("historial") or [{"de": None, "a": t["estado"], "por": "cowork",
                                                     "en": "2026-10-22T10:00:00-03:00", "motivo": "creada"}]
            reg.agregar(t)
        reg.guardar()


class PruebaReinicio(BaseReinicio):
    def test_reinicio_con_una_tarea_en_curso(self):
        self.instalar()
        entrada = self.cowork / "demo" / "entrada"
        entrada.mkdir(parents=True, exist_ok=True)
        (entrada / "01.json").write_text(json.dumps({"op": "crear", "tareas": [
            {"id": "T-3", "titulo": "t", "prompt": "#guion: colgado", "agente": "cc", "cambio": "login"}]}),
            encoding="utf-8")
        orq = subprocess.Popen([sys.executable, str(RAIZ_REPO / "orq.py"), "correr", "--sin-tablero"],
                               env=os.environ.copy(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            ruta = self.raiz / "proyectos" / "demo" / "tareas.json"
            limite, tarea = time.monotonic() + 60, None
            while time.monotonic() < limite:
                try:
                    tarea = json.loads(ruta.read_text(encoding="utf-8"))["tareas"][0]
                    if tarea["estado"] == "en_curso" and tarea["corridas"][-1]["pid"] and self.lanzamientos():
                        break
                except (OSError, ValueError, KeyError, IndexError):
                    pass
                time.sleep(0.2)
            self.assertEqual(tarea["estado"], "en_curso", "el orquestador no llegó a lanzar la tarea")
            pid_agente = tarea["corridas"][-1]["pid"]
            orq.kill()  # corte de golpe
            orq.wait(15)
        finally:
            if orq.poll() is None:
                orq.kill()
                orq.wait(15)
        self.assertTrue(esperar_muerto(pid_agente), "el agente sobrevivió al orquestador")
        sesion = self.lanzamientos()[0]["argv"][self.lanzamientos()[0]["argv"].index("--session-id") + 1]
        historial_antes = len(tarea["historial"])

        nuevo = self.orquestador()  # toma el candado abandonado y recupera
        t = self.tarea(nuevo, "T-3")
        self.assertEqual((t["estado"], t["interrupciones"], t["motivo"]), ("pendiente", 1, "interrumpida"))
        self.assertEqual(t["intentos"], 0)
        self.assertEqual(len(t["historial"]), historial_antes + 1)
        self.esperar(nuevo, lambda: len(self.lanzamientos()) == 2, mensaje="segundo lanzamiento")
        segundo = self.lanzamientos()[1]
        self.assertEqual(segundo["argv"][segundo["argv"].index("--resume") + 1], sesion)
        self.assertIn("se interrumpió", segundo["stdin"])

    def test_tercera_interrupcion(self):
        self.instalar()
        self.escribir_tareas({"id": "T-3", "estado": "en_curso", "interrupciones": 2, "intentos": 1,
                              "corridas": [{"intento": 3, "pid": None}]})
        orq = self.orquestador()
        t = self.tarea(orq, "T-3")
        self.assertEqual((t["estado"], t["motivo"]), ("fallida", "interrumpida demasiadas veces"))

    def test_proceso_anterior_vivo_se_termina(self):
        self.instalar()
        sobreviviente = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        self.addCleanup(lambda: (sobreviviente.kill(), sobreviviente.wait(10)))
        creado = procesos.hora_creacion(sobreviviente.pid)
        self.escribir_tareas({"id": "T-3", "estado": "en_curso", "intentos": 1,
                              "corridas": [{"intento": 1, "pid": sobreviviente.pid, "creado": creado}]})
        self.orquestador()
        self.assertTrue(esperar_muerto(sobreviviente.pid))

    def test_pid_reutilizado_no_se_mata(self):
        self.instalar()
        ajeno = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        self.addCleanup(lambda: (ajeno.kill(), ajeno.wait(10)))
        self.escribir_tareas({"id": "T-3", "estado": "en_curso", "intentos": 1,
                              "corridas": [{"intento": 1, "pid": ajeno.pid, "creado": 12345}]})
        self.orquestador()
        time.sleep(0.5)
        self.assertTrue(procesos.proceso_vivo(ajeno.pid), "no debe matar un proceso ajeno con el pid reutilizado")

    def test_estado_intacto_tras_reinicio(self):
        self.instalar()
        tareas = [{"id": f"T-{e}", "cambio": e.replace("_", "-"), "estado": e}
                  for e in ("bloqueada", "esperando_gate", "hecha", "fallida", "cancelada")]
        self.escribir_tareas(*[dict(t) for t in tareas])
        antes = json.loads((self.raiz / "proyectos" / "demo" / "tareas.json").read_text(encoding="utf-8"))["tareas"]
        orq = self.orquestador()
        for t in antes:
            self.assertEqual(self.tarea(orq, t["id"]), t)

    def test_cancelacion_pedida_antes_del_corte(self):
        self.instalar()
        self.escribir_tareas({"id": "T-3", "estado": "en_curso", "intentos": 1, "corridas": [{"intento": 1}],
                              "cancelacion": {"por": "cowork", "via": "entrada", "pedida": "2026-10-22T10:01:00-03:00"}})
        orq = self.orquestador()
        t = self.tarea(orq, "T-3")
        self.assertEqual(t["estado"], "cancelada")
        self.assertEqual(t["historial"][-1]["por"], "cowork")


if __name__ == "__main__":
    unittest.main()
