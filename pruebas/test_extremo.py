"""Tarea 9.2: de extremo a extremo con el falso de cc y la red bloqueada (salvo 127.0.0.1 para el tablero).

Lote de Cowork con dependencias → corte del orquestador a mitad de una corrida y reinicio → gate aprobado por el
flujo completo del tablero → límite del plan y espera → salida de Cowork actualizada y tablero leyendo todo.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import socket
import unittest

from ayudantes import PruebaOrq, RedBloqueada

CODIGO = re.compile(r"Código para aprobar demo/T-1 \(huella [0-9a-f]{12}\): (\d{6})")


class PruebaExtremoAExtremo(PruebaOrq):
    def test_flujo_completo(self):
        with self.assertRaises(RedBloqueada):
            socket.create_connection(("192.0.2.10", 443), timeout=1)
        self.instalar(config={"limites": {"global": 2, "por_agente": {"cc": 2}}},
                      proyecto={"limites": {"por_agente": {"cc": 2}}})
        desfase = [dt.timedelta(0)]

        def reloj():
            return dt.datetime.now().astimezone() + desfase[0]

        # 1. Lote de Cowork con una dependencia; T-1 pide gate.
        orq1 = self.orquestador(reloj=reloj, codigo_modificado=[])
        self.pedir(orq1, {"id": "T-1", "cambio": "login", "prompt": "#guion: ok", "gate": {"requiere": True}},
                   {"id": "T-2", "cambio": "reportes", "prompt": "#guion: limite_una_vez", "dependencias": ["T-1"]},
                   {"id": "T-3", "cambio": "pagos", "prompt": "#guion: colgado_una_vez"})
        self.esperar(orq1, lambda: self.tarea(orq1, "T-1")["estado"] == "esperando_gate"
                     and len(self.lanzamientos()) == 2, timeout=90,
                     mensaje=lambda: {i: (self.tarea(orq1, i)["estado"], self.tarea(orq1, i)["motivo"])
                                      for i in ("T-1", "T-2", "T-3")} | {"lanzamientos": len(self.lanzamientos())})
        self.assertEqual(self.tarea(orq1, "T-2")["estado"], "bloqueada")
        self.assertEqual(self.tarea(orq1, "T-3")["estado"], "en_curso")

        # 2. Corte a mitad de T-3 y reinicio: el estado sobrevive y T-3 vuelve a correr.
        orq1.detener()
        orq1.ctx.cerrar()
        orq2 = self.orquestador(reloj=reloj, codigo_modificado=[])
        t3 = self.tarea(orq2, "T-3")
        self.assertEqual((t3["estado"], t3["interrupciones"]), ("pendiente", 1))
        self.assertEqual(self.tarea(orq2, "T-1")["estado"], "esperando_gate")
        _, cliente, _ = self.tablero(orq2)
        self.bucle(orq2)
        self.esperar_que(lambda: self.tarea(orq2, "T-3")["estado"] == "hecha", timeout=60, mensaje="T-3 hecha")

        # 3. Gate de T-1 por el flujo completo del tablero.
        huella = self.tarea(orq2, "T-1")["gate"]["huella"]
        detalle = cliente.json("/api/tareas/demo/T-1")[1]
        self.assertEqual(detalle["gate"]["huella"], huella)
        self.assertTrue(detalle["diff_disponible"])
        self.assertEqual(cliente.gate("demo", "T-1", "preparar", {"decision": "aprobar", "huella": huella})[0], 200)
        codigo = [m.group(1) for x in self.terminal for m in [CODIGO.search(x)] if m][-1]
        estado, datos = cliente.gate("demo", "T-1", "confirmar", {"decision": "aprobar", "huella": huella,
                                                                   "codigo": codigo})
        self.assertEqual(estado, 200, datos)

        # 4. T-2 se desbloquea y choca con el límite del plan; el tablero lo muestra.
        self.esperar_que(lambda: self.tarea(orq2, "T-2")["limites_plan"] == 1, timeout=60, mensaje="límite de T-2")
        self.assertEqual(self.tarea(orq2, "T-2")["estado"], "pendiente")
        self.esperar_que(lambda: [c for c in cliente.json("/api/tareas")[1]["tarjetas"]
                                  if c["id"] == "T-2" and c["plan_agotado_hasta"]], timeout=10,
                         mensaje="tarjeta con plan agotado")

        # 5. Pasa el tiempo: el plan se repone y T-2 termina.
        desfase[0] = dt.timedelta(hours=2)
        self.esperar_que(lambda: self.tarea(orq2, "T-2")["estado"] == "hecha", timeout=60, mensaje="T-2 hecha")

        # 6. Salida de Cowork actualizada.
        salida = self.cowork / "demo" / "salida"
        self.esperar_que(lambda: {t["id"]: t["estado"] for t in json.loads(
            (salida / "estado.json").read_text(encoding="utf-8"))["tareas"]} ==
            {"T-1": "hecha", "T-2": "hecha", "T-3": "hecha"}, timeout=10, mensaje="salida de Cowork al día")
        estado_cowork = json.loads((salida / "estado.json").read_text(encoding="utf-8"))
        t1 = next(t for t in estado_cowork["tareas"] if t["id"] == "T-1")
        self.assertEqual((t1["gate"]["decision"], t1["gate"]["huella_corta"]), ("aprobada", huella[:12]))
        for id_tarea in ("T-1", "T-2", "T-3"):
            self.assertTrue((salida / "resultados" / f"{id_tarea}.md").exists())
            self.assertTrue((salida / "diffstat" / f"{id_tarea}.json").exists())
        tipos = {e["tipo"] for e in json.loads((salida / "eventos-recientes.json").read_text(encoding="utf-8"))["eventos"]}
        self.assertLessEqual({"inicio", "archivo", "comando", "fin", "gate", "error"}, tipos)
        consumo = json.loads((salida / "consumo.json").read_text(encoding="utf-8"))["por_agente_y_dia"]["cc"]
        self.assertEqual(sum(d["limites"] for d in consumo.values()), 1)

        # 7. El tablero lee todo.
        tarjetas = cliente.json("/api/tareas")[1]["tarjetas"]
        self.assertEqual({c["id"]: c["estado"] for c in tarjetas}, {"T-1": "hecha", "T-2": "hecha", "T-3": "hecha"})
        uso = cliente.json("/api/consumo")[1]["agentes"][0]
        self.assertEqual((uso["agente"], uso["tareas"], uso["limites"]), ("cc", 3, 1))
        self.assertIn("(estimado)", uso["costo_texto"])
        t2 = cliente.json("/api/tareas/demo/T-2")[1]
        self.assertEqual((t2["limites_plan"], t2["estado"]), (1, "hecha"))
        eventos = cliente.json("/api/tareas/demo/T-2/eventos?desde=0")[1]["eventos"]
        self.assertTrue([e for e in eventos if e["tipo"] == "fin"])


if __name__ == "__main__":
    unittest.main()
