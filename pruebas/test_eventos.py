"""Tarea 3.1: registro JSONL de eventos (spec eventos-actividad)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orquestador import eventos
from orquestador.redaccion import MARCA_TRUNCADO

MOMENTO = "2026-10-22T10:00:00-03:00"


class BaseEventos(unittest.TestCase):
    def setUp(self):
        temporal = tempfile.TemporaryDirectory(prefix="orq-eventos-", ignore_cleanup_errors=True)
        self.addCleanup(temporal.cleanup)
        self.carpeta = Path(temporal.name)
        self.escritor = self.nuevo()

    def nuevo(self, **opciones):
        return eventos.EscritorEventos(self.carpeta, "demo", reloj=lambda: MOMENTO, **opciones)

    @property
    def archivo(self) -> Path:
        return self.carpeta / "eventos.jsonl"

    def lineas(self):
        return [json.loads(x) for x in self.archivo.read_text(encoding="utf-8").splitlines()]


class PruebaAppendOnly(BaseEventos):
    def test_evento_agregado_es_una_linea_al_final(self):
        self.escritor.escribir("inicio", {"sesion": "s1", "modelo": "m", "retomada": False}, tarea="T-1",
                               intento=1, agente="cc")
        antes = self.archivo.read_bytes()
        self.escritor.escribir("archivo", {"ruta": "app.py", "accion": "editar"}, tarea="T-1", intento=1,
                               agente="cc")
        despues = self.archivo.read_bytes()
        self.assertTrue(despues.startswith(antes))
        self.assertEqual(despues.count(b"\n") - antes.count(b"\n"), 1)
        self.assertTrue(despues.endswith(b"\n"))

    def test_lector_ignora_la_linea_incompleta(self):
        self.escritor.escribir("mensaje", {"texto": "hola"}, tarea="T-1", intento=1, agente="cc")
        with open(self.archivo, "ab") as f:
            f.write(b'{"v": 1, "tipo": "mens')  # a medio escribir
        leidos, offset = eventos.leer_desde(self.archivo, 0)
        self.assertEqual([e["tipo"] for e in leidos], ["mensaje"])
        with open(self.archivo, "ab") as f:
            f.write(b'aje"}\n')
        nuevos, offset2 = eventos.leer_desde(self.archivo, offset)
        self.assertEqual(len(nuevos), 1)
        self.assertGreater(offset2, offset)
        self.assertEqual(eventos.leer_desde(self.archivo, offset2)[0], [])

    def test_lector_sin_archivo(self):
        self.assertEqual(eventos.leer_desde(self.carpeta / "no.jsonl", 0), ([], 0))


class PruebaEsquema(BaseEventos):
    def test_campos_comunes(self):
        e = self.escritor.escribir("comando", {"comando": "py -3.12 -m unittest", "estado": "ok", "codigo_salida": 0},
                                   tarea="T-12", intento=2, agente="cc")
        self.assertEqual(set(e), {"v", "ts", "proyecto", "tarea", "intento", "agente", "seq", "tipo", "datos"})
        self.assertEqual((e["v"], e["ts"], e["proyecto"], e["tarea"], e["intento"], e["agente"], e["tipo"]),
                         (1, MOMENTO, "demo", "T-12", 2, "cc", "comando"))
        self.assertEqual(self.lineas()[0], e)

    def test_campos_por_tipo(self):
        casos = {
            "inicio": {"sesion": "s", "modelo": "m", "retomada": True},
            "mensaje": {"texto": "listo"},
            "herramienta": {"nombre": "leer", "objetivo": "src/a.py", "estado": "ok"},
            "archivo": {"ruta": "src/a.py", "accion": "editar"},
            "comando": {"comando": "git status", "estado": "ok", "codigo_salida": 0},
            "fin": {"ok": True, "duracion_s": 12, "consumo": {"tokens_entrada": 10, "tokens_salida": 5,
                                                             "costo_usd": 0.1, "costo_estimado": True}},
            "error": {"clase": "timeout", "mensaje": "se acabó el tiempo"},
            "gate": {"decision": "aprobada", "huella": "3fa9c1d2e4b5", "via": "tablero", "sesion": "ab12"},
        }
        for tipo, datos in casos.items():
            with self.subTest(tipo=tipo):
                e = self.escritor.escribir(tipo, dict(datos, intruso="no va"), tarea="T-1", intento=1, agente="cc")
                for clave in datos:
                    self.assertIn(clave, e["datos"])
                self.assertNotIn("intruso", e["datos"])

    def test_tipo_desconocido(self):
        with self.assertRaises(ValueError):
            self.escritor.escribir("salida_cruda", {"x": 1})

    def test_evento_desconocido_del_agente_se_cuenta(self):
        for _ in range(3):
            self.escritor.ignorado("T-1", 1)
        self.escritor.ignorado("T-1", 2)
        fin = self.escritor.escribir("fin", {"ok": True, "duracion_s": 1}, tarea="T-1", intento=1, agente="cc")
        self.assertEqual(fin["datos"]["eventos_ignorados"], 3)
        self.assertEqual(len(self.lineas()), 1)

    def test_seq_monotono_y_se_recupera(self):
        for i in range(3):
            self.escritor.escribir("mensaje", {"texto": str(i)}, tarea="T-1", intento=1, agente="cc")
        otro = self.nuevo()
        e = otro.escribir("mensaje", {"texto": "x"}, tarea="T-1", intento=1, agente="cc")
        self.assertEqual([x["seq"] for x in self.lineas()], [1, 2, 3, 4])
        self.assertEqual(e["seq"], 4)

    def test_evento_del_orquestador_sin_agente(self):
        e = self.escritor.escribir("error", {"clase": "seguridad", "mensaje": "gate por archivo"})
        self.assertIsNone(e["agente"])
        self.assertIsNone(e["intento"])


class PruebaSinContenidoNiSecretos(BaseEventos):
    def test_lectura_de_archivo_de_datos(self):
        e = self.escritor.escribir("herramienta", {"nombre": "leer", "objetivo": "datos/clientes.csv", "estado": "ok",
                                                   "contenido": "rut;nombre\n1-9;Cliente Sintético",
                                                   "resultado": "1-9;Cliente"}, tarea="T-1", intento=1, agente="cc")
        self.assertEqual(e["datos"], {"nombre": "leer", "objetivo": "datos/clientes.csv", "estado": "ok"})
        self.assertNotIn("Cliente", self.archivo.read_text(encoding="utf-8"))

    def test_secreto_en_un_comando(self):
        comando = ("curl -H 'Authorization: Bearer abcdef0123456789abcdef' -d k=sk-ant-api03-ZZZsintetico0123456 "
                   "ghp_a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8 AKIAIOSFODNN7EXAMPLE")
        e = self.escritor.escribir("comando", {"comando": comando, "estado": "ok", "codigo_salida": 0}, tarea="T-1",
                                   intento=1, agente="cc")
        texto = self.archivo.read_text(encoding="utf-8")
        for secreto in ("abcdef0123456789abcdef", "ZZZsintetico0123456", "a1B2c3D4e5F6", "AKIAIOSFODNN7EXAMPLE"):
            self.assertNotIn(secreto, texto)
        self.assertIn("[REDACTADO]", e["datos"]["comando"])

    def test_llave_pem_en_un_mensaje(self):
        self.escritor.escribir("mensaje", {"texto": "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADsintetico\n"
                                                    "-----END PRIVATE KEY-----"}, tarea="T-1", intento=1, agente="cc")
        self.assertNotIn("MIIEvQIBADsintetico", self.archivo.read_text(encoding="utf-8"))

    def test_patron_extra_del_proyecto(self):
        escritor = self.nuevo(patrones_extra=[r"CL-\d{6}"])
        escritor.escribir("mensaje", {"texto": "revisé CL-123456"}, tarea="T-1", intento=1, agente="cc")
        self.assertNotIn("CL-123456", self.archivo.read_text(encoding="utf-8"))

    def test_proyecto_sin_texto_de_mensajes(self):
        escritor = self.nuevo(texto_mensajes="nunca")
        e = escritor.escribir("mensaje", {"texto": "contenido que no debe quedar"}, tarea="T-1", intento=1,
                              agente="cc")
        self.assertEqual(e["datos"], {"largo": len("contenido que no debe quedar")})
        self.assertNotIn("contenido que no", self.archivo.read_text(encoding="utf-8"))


class PruebaTopeDeLinea(BaseEventos):
    def test_mensaje_de_50000_caracteres(self):
        self.escritor.escribir("mensaje", {"texto": "a" * 50_000}, tarea="T-1", intento=1, agente="cc")
        linea = self.archivo.read_bytes()
        self.assertLessEqual(len(linea), eventos.TOPE_LINEA)
        self.assertTrue(self.lineas()[0]["datos"]["texto"].endswith(MARCA_TRUNCADO))

    def test_caracteres_de_varios_bytes(self):
        self.escritor.escribir("mensaje", {"texto": "ñ€" * 50_000}, tarea="T-1", intento=1, agente="cc")
        self.assertLessEqual(len(self.archivo.read_bytes()), eventos.TOPE_LINEA)

    def test_varios_campos_largos(self):
        self.escritor.escribir("comando", {"comando": "x" * 9000, "estado": "y" * 9000, "codigo_salida": 1},
                               tarea="T-1", intento=1, agente="cc")
        self.assertLessEqual(len(self.archivo.read_bytes()), eventos.TOPE_LINEA)


class PruebaRutas(unittest.TestCase):
    def test_ruta_relativa_al_worktree(self):
        wt = Path("C:/work/wt-login")
        self.assertEqual(eventos.ruta_para_evento(wt / "src" / "a.py", wt, home=Path("C:/Users/x")), "src/a.py")

    def test_ruta_fuera_del_worktree_en_el_home(self):
        self.assertEqual(eventos.ruta_para_evento(Path("C:/Users/x/.ssh/id_rsa"), Path("C:/work/wt"),
                                                  home=Path("C:/Users/x")), "~/.ssh/id_rsa")

    def test_ruta_fuera_de_todo(self):
        self.assertEqual(eventos.ruta_para_evento(Path("D:/otro/a.txt"), Path("C:/work/wt"), home=Path("C:/Users/x")),
                         "D:/otro/a.txt")


if __name__ == "__main__":
    unittest.main()
