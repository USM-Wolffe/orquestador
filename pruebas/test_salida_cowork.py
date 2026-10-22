"""Tarea 7.1: salida de solo lectura para Cowork (spec estado-cowork): avance en 2 s, eventos acotados, secretos
sembrados, archivo de datos y salida editada por Cowork."""
from __future__ import annotations

import hashlib
import json
import os
import time
import unittest

from ayudantes import PruebaOrq


class BaseSalida(PruebaOrq):
    def salida(self, nombre: str = "estado.json"):
        return json.loads((self.cowork / "demo" / "salida" / nombre).read_text(encoding="utf-8"))

    def archivos_salida(self):
        return [r for r in (self.cowork / "demo" / "salida").rglob("*") if r.is_file()]


class PruebaAvance(BaseSalida):
    def test_cowork_lee_el_avance(self):
        self.instalar(proyecto={"gate_por_defecto": True})
        orq = self.orquestador(codigo_modificado=[])
        prompt = "#guion: ok\nAgrega el saludo."
        self.pedir(orq, {"id": "T-1", "prompt": prompt})
        self.esperar(orq, lambda: self.tarea(orq, "T-1")["estado"] == "esperando_gate", timeout=60,
                     mensaje="esperando gate")
        visto = time.monotonic()
        while time.monotonic() - visto < 2.0:
            t = self.salida()["tareas"][0]
            if t["estado"] == "esperando_gate":
                break
            time.sleep(0.1)
        self.assertEqual(t["estado"], "esperando_gate")
        self.assertEqual(t["gate"]["huella_corta"], self.tarea(orq, "T-1")["gate"]["huella"][:12])
        self.assertNotIn("prompt", t)
        self.assertEqual(t["prompt_sha256"], hashlib.sha256(prompt.encode("utf-8")).hexdigest())
        informe = (self.cowork / "demo" / "salida" / "resultados" / "T-1.md").read_text(encoding="utf-8")
        self.assertEqual(informe, "Listo: edité app.py y las pruebas pasan.")
        diff = self.salida("diffstat/T-1.json")
        self.assertIn({"ruta": "app.py", "agregadas": 1, "borradas": 0, "nuevo": True, "binario": False},
                      diff["archivos"])
        consumo = self.salida("consumo.json")["por_agente_y_dia"]["cc"]
        self.assertEqual(list(consumo.values())[0]["tokens_entrada"], 1200)
        self.assertTrue(self.salida()["latido"])
        self.assertTrue(self.salida()["agentes"]["cc"]["disponible"])

    def test_eventos_recientes_acotados(self):
        self.instalar()
        orq = self.orquestador()
        escritor = orq.proyectos["demo"].escritor
        for i in range(5000):
            escritor.escribir("mensaje", {"texto": f"mensaje {i} " + "x" * 900}, tarea="T-1", intento=1 + i // 1000,
                              agente="cc")
        orq.ciclo()
        eventos = self.salida("eventos-recientes.json")["eventos"]
        self.assertEqual(len(eventos), 300)
        self.assertEqual(eventos[-1]["seq"], 5000)
        self.assertTrue(all(len(e["datos"]["texto"]) <= 500 for e in eventos))


class PruebaSinSecretos(BaseSalida):
    SECRETOS = {
        "entorno con formato": "sk-ant-api03-ENTORNOSINTETICO0123456789",
        "entorno sin formato": "ENTORNO-SECRETO-5521",
        "prompt": "PROMPT-SECRETO-4471",
        "stderr": "SECRETO-STDERR-7731",
        "comando": "ghp_COMANDOSINTETICO0123456789abcd",
    }

    def test_secretos_sembrados(self):
        guardado = {k: os.environ.get(k) for k in ("ANTHROPIC_API_KEY", "EMBUDO_CLAVE")}
        self.addCleanup(lambda: [os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
                                 for k, v in guardado.items()])
        os.environ["ANTHROPIC_API_KEY"] = self.SECRETOS["entorno con formato"]
        os.environ["EMBUDO_CLAVE"] = self.SECRETOS["entorno sin formato"]
        self.instalar()
        orq = self.orquestador()
        self.poner_tarea(orq, id="T-1", max_intentos=1,
                         prompt=f"#guion: secretos\nUsa la clave {self.SECRETOS['prompt']} para el repo.")
        self.esperar(orq, lambda: self.tarea(orq, "T-1")["estado"] == "fallida", timeout=60, mensaje="T-1 fallida")
        orq.ciclo()
        # El stderr con el secreto sí quedó en el estado interno (la redacción por patrones no lo reconoce):
        internos = (orq.proyectos["demo"].proyecto.carpeta_eventos / "eventos.jsonl").read_text(encoding="utf-8")
        self.assertIn(self.SECRETOS["stderr"], internos)
        for archivo in self.archivos_salida():
            contenido = archivo.read_text(encoding="utf-8")
            for origen, secreto in self.SECRETOS.items():
                self.assertNotIn(secreto, contenido, f"secreto del {origen} en {archivo.name}")
        eventos = self.salida("eventos-recientes.json")["eventos"]
        comandos = [e for e in eventos if e["tipo"] == "comando"]
        self.assertIn("[REDACTADO]", comandos[0]["datos"]["comando"])
        self.assertIn({"clase": "agente"}, [e["datos"] for e in eventos if e["tipo"] == "error"])
        self.assertEqual(self.salida()["tareas"][0]["resultado"]["error_clase"], "error")
        self.assertNotIn("mensaje", json.dumps(self.salida()["tareas"][0]["resultado"]))

    def test_archivo_de_datos_leido_por_el_agente(self):
        self.instalar()
        orq = self.orquestador()
        self.pedir(orq, {"id": "T-1", "prompt": "#guion: lectura"})
        self.esperar(orq, lambda: self.tarea(orq, "T-1")["estado"] == "hecha", timeout=60, mensaje="T-1 hecha")
        eventos = self.salida("eventos-recientes.json")["eventos"]
        lectura = [e for e in eventos if e["tipo"] == "herramienta"]
        self.assertEqual(lectura[0]["datos"]["objetivo"], "datos/clientes.csv")
        for archivo in self.archivos_salida():
            self.assertNotIn("Cliente Sintético", archivo.read_text(encoding="utf-8"))


class PruebaNuncaLeeLaSalida(BaseSalida):
    def test_cowork_edita_la_salida(self):
        self.instalar()
        orq = self.orquestador()
        self.poner_tarea(orq, id="T-1")
        orq.ciclo()
        ruta = self.cowork / "demo" / "salida" / "estado.json"
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        datos["tareas"][0]["estado"] = "hecha"
        ruta.write_text(json.dumps(datos), encoding="utf-8")
        resultados = self.cowork / "demo" / "salida" / "resultados"
        resultados.mkdir(parents=True, exist_ok=True)
        orq.ciclo()
        self.assertNotEqual(self.tarea(orq, "T-1")["estado"], "hecha")
        self.assertEqual(self.salida()["tareas"][0]["estado"], self.tarea(orq, "T-1")["estado"])


if __name__ == "__main__":
    unittest.main()
