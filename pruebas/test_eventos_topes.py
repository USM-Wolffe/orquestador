"""Tarea 3.2: tope de eventos de detalle por intento y rotación por tamaño (spec eventos-actividad)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ayudantes import PruebaOrq

from orquestador import config as cfg
from orquestador import eventos

MOMENTO = "2026-10-22T10:00:00-03:00"


class BaseTopes(unittest.TestCase):
    def setUp(self):
        temporal = tempfile.TemporaryDirectory(prefix="orq-topes-", ignore_cleanup_errors=True)
        self.addCleanup(temporal.cleanup)
        self.carpeta = Path(temporal.name)

    def escritor(self, **opciones):
        return eventos.EscritorEventos(self.carpeta, "demo", reloj=lambda: MOMENTO, **opciones)

    def lineas(self, nombre="eventos.jsonl"):
        return [json.loads(x) for x in (self.carpeta / nombre).read_text(encoding="utf-8").splitlines()]


class PruebaTopePorIntento(BaseTopes):
    def test_agente_muy_conversador(self):
        e = self.escritor()
        for i in range(3000):
            e.escribir("herramienta", {"nombre": "leer", "objetivo": f"a{i}.py", "estado": "ok"}, tarea="T-1",
                       intento=1, agente="cc")
        fin = e.escribir("fin", {"ok": True, "duracion_s": 5}, tarea="T-1", intento=1, agente="cc")
        lineas = self.lineas()
        self.assertEqual(sum(1 for x in lineas if x["tipo"] == "herramienta"), 2000)
        self.assertEqual(fin["datos"]["eventos_omitidos"], 1000)

    def test_archivo_error_y_fin_siempre_se_escriben(self):
        e = self.escritor(tope_detalle=3)
        for tipo, datos in [("mensaje", {"texto": "1"}), ("comando", {"comando": "a", "estado": "ok"}),
                            ("herramienta", {"nombre": "leer"}), ("mensaje", {"texto": "omitido"}),
                            ("comando", {"comando": "omitido", "estado": "ok"}),
                            ("archivo", {"ruta": "a.py", "accion": "editar"}),
                            ("error", {"clase": "agente", "mensaje": "x"})]:
            e.escribir(tipo, datos, tarea="T-1", intento=1, agente="cc")
        e.escribir("fin", {"ok": False, "duracion_s": 1}, tarea="T-1", intento=1, agente="cc")
        tipos = [x["tipo"] for x in self.lineas()]
        self.assertEqual(tipos, ["mensaje", "comando", "herramienta", "archivo", "error", "fin"])
        self.assertEqual(self.lineas()[-1]["datos"]["eventos_omitidos"], 2)

    def test_el_tope_es_por_intento(self):
        e = self.escritor(tope_detalle=2)
        for intento in (1, 2):
            for _ in range(3):
                e.escribir("mensaje", {"texto": "x"}, tarea="T-1", intento=intento, agente="cc")
        self.assertEqual(len(self.lineas()), 4)
        e.escribir("mensaje", {"texto": "x"}, tarea="T-2", intento=1, agente="cc")
        self.assertEqual(len(self.lineas()), 5)

    def test_fin_sin_omitidos_no_trae_el_campo(self):
        e = self.escritor()
        fin = e.escribir("fin", {"ok": True, "duracion_s": 1}, tarea="T-1", intento=1, agente="cc")
        self.assertNotIn("eventos_omitidos", fin["datos"])


class PruebaRotacion(BaseTopes):
    def llenar(self, e, n):
        for i in range(n):
            e.escribir("mensaje", {"texto": f"evento {i} " + "x" * 200}, tarea="T-1", intento=1, agente="cc")

    def test_supera_el_tope(self):
        e = self.escritor(tope_bytes=2000)
        archivo = self.carpeta / "eventos.jsonl"
        while not archivo.exists() or archivo.stat().st_size <= 2000:
            self.llenar(e, 1)
        self.assertFalse((self.carpeta / "eventos.1.jsonl").exists(), "no debe rotar en medio de la escritura")
        antes = (self.carpeta / "eventos.jsonl").read_bytes()
        e.escribir("mensaje", {"texto": "siguiente"}, tarea="T-1", intento=1, agente="cc")
        self.assertEqual((self.carpeta / "eventos.1.jsonl").read_bytes(), antes)
        self.assertEqual([x["datos"]["texto"] for x in self.lineas()], ["siguiente"])

    def test_ya_hay_cinco_rotados(self):
        for n in range(1, 6):
            (self.carpeta / f"eventos.{n}.jsonl").write_text(json.dumps({"rotado": n}) + "\n", encoding="utf-8")
        e = self.escritor(tope_bytes=500, rotados=5)
        self.llenar(e, 3)
        e.escribir("mensaje", {"texto": "nuevo"}, tarea="T-1", intento=1, agente="cc")
        self.assertFalse((self.carpeta / "eventos.6.jsonl").exists())
        self.assertEqual(self.lineas("eventos.5.jsonl"), [{"rotado": 4}])
        self.assertEqual(self.lineas("eventos.2.jsonl"), [{"rotado": 1}])
        self.assertEqual(self.lineas("eventos.1.jsonl")[0]["datos"]["texto"].split()[0], "evento")

    def test_rotacion_entre_lineas(self):
        e = self.escritor(tope_bytes=700, rotados=3)
        self.llenar(e, 40)
        for archivo in self.carpeta.glob("eventos*.jsonl"):
            contenido = archivo.read_bytes()
            self.assertTrue(contenido.endswith(b"\n"), archivo.name)
            for linea in contenido.splitlines():
                json.loads(linea)
        self.assertFalse((self.carpeta / "eventos.4.jsonl").exists())

    def test_seq_continua_despues_de_rotar(self):
        e = self.escritor(tope_bytes=500)
        self.llenar(e, 6)
        otro = self.escritor(tope_bytes=500)
        siguiente = otro.escribir("mensaje", {"texto": "x"}, tarea="T-1", intento=1, agente="cc")
        self.assertEqual(siguiente["seq"], 7)


class PruebaTopesPorConfiguracion(PruebaOrq):
    def test_config_define_tope_y_rotados(self):
        repo = self.crear_repo()
        self.escribir_config(eventos={"tope_mb": 0.002, "rotados": 2})
        self.escribir_proyecto("demo", repo)
        from orquestador import proyectos as proy
        config = cfg.cargar_config()
        proyecto = proy.cargar_proyectos(config)[0]
        e = eventos.EscritorEventos.para_proyecto(config, proyecto)
        self.assertEqual((e.tope_bytes, e.rotados), (int(0.002 * 1024 * 1024), 2))
        for i in range(60):
            e.escribir("mensaje", {"texto": "y" * 300}, tarea="T-1", intento=1, agente="cc")
        self.assertTrue((proyecto.carpeta_eventos / "eventos.2.jsonl").exists())
        self.assertFalse((proyecto.carpeta_eventos / "eventos.3.jsonl").exists())

    def test_texto_mensajes_del_proyecto(self):
        repo = self.crear_repo()
        self.escribir_config()
        self.escribir_proyecto("demo", repo, eventos={"texto_mensajes": "nunca"})
        from orquestador import proyectos as proy
        config = cfg.cargar_config()
        e = eventos.EscritorEventos.para_proyecto(config, proy.cargar_proyectos(config)[0])
        self.assertEqual(e.escribir("mensaje", {"texto": "abc"}, tarea="T-1", intento=1)["datos"], {"largo": 3})

    def test_rotacion_postergada_queda_en_registro_log(self):
        # El tablero o Cowork pueden tener eventos.jsonl abierto: Windows niega el reemplazo y se posterga.
        repo = self.crear_repo()
        self.escribir_config(eventos={"tope_mb": 0.001, "rotados": 2})
        self.escribir_proyecto("demo", repo)
        from orquestador import proyectos as proy
        config = cfg.cargar_config()
        proyecto = proy.cargar_proyectos(config)[0]
        e = eventos.EscritorEventos.para_proyecto(config, proyecto)
        with mock.patch("orquestador.eventos.reemplazar", side_effect=PermissionError(13, "archivo en uso")):
            for _ in range(10):
                e.escribir("mensaje", {"texto": "z" * 300}, tarea="T-1", intento=1, agente="cc")
        self.assertFalse((proyecto.carpeta_eventos / "eventos.1.jsonl").exists())
        registro_log = (self.raiz / "registro.log").read_text(encoding="utf-8")
        self.assertIn("rotación de eventos postergada", registro_log)
        self.assertIn("demo", registro_log)


if __name__ == "__main__":
    unittest.main()
