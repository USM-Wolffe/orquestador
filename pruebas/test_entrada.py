"""Tarea 2.3: entrada de solicitudes de Cowork y trabajos v0 (specs registro-tareas, compatibilidad-v0 y
proyectos "Ruta libre en una tarea")."""
from __future__ import annotations

import json
import unittest

from ayudantes import PruebaOrq

from orquestador import config as cfg
from orquestador import entrada, registro
from orquestador import proyectos as proy

MOMENTO = "2026-10-22T10:00:00-03:00"


class Reloj:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class BaseEntrada(PruebaOrq):
    def setUp(self):
        super().setUp()
        self.repo = self.crear_repo()
        self.escribir_config()
        self.escribir_proyecto("demo", self.repo)
        self.config = cfg.cargar_config()
        self.proyecto = proy.cargar_proyectos(self.config)[0]
        for sub in ("entrada", "respuestas", "salida"):
            (self.proyecto.carpeta_cowork / sub).mkdir(parents=True, exist_ok=True)
        self.proyecto.carpeta.mkdir(parents=True, exist_ok=True)
        self.reg = registro.Registro(self.proyecto.ruta_tareas)
        self.reg.cargar()
        self.reloj = Reloj()
        self.eventos = []
        self.procesador = entrada.ProcesadorEntrada(
            self.proyecto, self.reg, self.config, reloj=self.reloj, momento=lambda: MOMENTO,
            al_evento=lambda tipo, datos, tarea=None: self.eventos.append((tipo, datos, tarea)))

    @property
    def carpeta_entrada(self):
        return self.proyecto.carpeta_cowork / "entrada"

    def dejar(self, nombre, datos):
        texto = datos if isinstance(datos, str) else json.dumps(datos, ensure_ascii=False)
        (self.carpeta_entrada / nombre).write_text(texto, encoding="utf-8")

    def acuse(self, nombre):
        return json.loads((self.proyecto.carpeta_cowork / "respuestas" / nombre).read_text(encoding="utf-8"))

    def tarea(self, id_tarea, **extra):
        datos = {"id": id_tarea, "titulo": f"Tarea {id_tarea}", "prompt": "Trabajo sintético", "agente": "cc",
                 "cambio": "login"}
        datos.update(extra)
        return datos

    def guardado(self, id_tarea):
        r = registro.Registro(self.proyecto.ruta_tareas)
        r.cargar()
        return r.obtener(id_tarea)


class PruebaCrear(BaseEntrada):
    def test_lote_con_dependencias(self):
        self.dejar("20261022-100000-lote.json", {"op": "crear", "tareas": [
            self.tarea("T-1"), self.tarea("T-2"), self.tarea("T-3", dependencias=["T-1", "T-2"])]})
        acuses = self.procesador.procesar()
        self.assertTrue(acuses[0]["ok"], acuses)
        self.assertEqual(self.guardado("T-1")["estado"], "pendiente")
        self.assertEqual(self.guardado("T-3")["estado"], "bloqueada")
        self.assertEqual(self.guardado("T-3")["historial"][0]["por"], "cowork")
        self.assertEqual(self.acuse("20261022-100000-lote.json")["ids"], ["T-1", "T-2", "T-3"])
        self.assertTrue((self.carpeta_entrada / "procesadas" / "20261022-100000-lote.json").exists())
        self.assertFalse((self.carpeta_entrada / "20261022-100000-lote.json").exists())

    def test_dependencia_hecha_no_bloquea(self):
        self.dejar("01.json", {"op": "crear", "tareas": [self.tarea("T-1")]})
        self.procesador.procesar()
        self.reg.obtener("T-1")["estado"] = "hecha"
        self.reg.guardar()
        self.dejar("02.json", {"op": "crear", "tareas": [self.tarea("T-2", dependencias=["T-1"])]})
        self.procesador.procesar()
        self.assertEqual(self.guardado("T-2")["estado"], "pendiente")

    def test_todo_o_nada(self):
        casos = {
            "inexistente.json": [self.tarea("T-1", dependencias=["T-99"])],
            "ciclo.json": [self.tarea("T-1", dependencias=["T-2"]), self.tarea("T-2", dependencias=["T-1"])],
            "repetido.json": [self.tarea("T-1"), self.tarea("T-1")],
            "uno-malo.json": [self.tarea("T-1"), self.tarea("T-2", agente="codex")],
        }
        for nombre, lote in casos.items():
            with self.subTest(caso=nombre):
                self.dejar(nombre, {"op": "crear", "tareas": lote})
                self.procesador.procesar()
                acuse = self.acuse(nombre)
                self.assertFalse(acuse["ok"])
                self.assertTrue(acuse["errores"])
                self.assertEqual(self.reg.lista(), [])

    def test_ciclo_con_tareas_existentes(self):
        self.dejar("01.json", {"op": "crear", "tareas": [self.tarea("T-1")]})
        self.procesador.procesar()
        self.dejar("02.json", {"op": "editar", "id": "T-1", "cambios": {"dependencias": ["T-2"]}})
        self.dejar("03.json", {"op": "crear", "tareas": [self.tarea("T-2", dependencias=["T-1"])]})
        self.procesador.procesar()
        self.assertFalse(self.acuse("02.json")["ok"])  # T-2 todavía no existe
        self.assertTrue(self.acuse("03.json")["ok"])
        self.dejar("04.json", {"op": "editar", "id": "T-1", "cambios": {"dependencias": ["T-2"]}})
        self.procesador.procesar()
        self.assertFalse(self.acuse("04.json")["ok"])
        self.assertIn("ciclo", " ".join(self.acuse("04.json")["errores"]))

    def test_id_repetido_con_el_registro(self):
        self.dejar("01.json", {"op": "crear", "tareas": [self.tarea("T-1")]})
        self.dejar("02.json", {"op": "crear", "tareas": [self.tarea("T-1")]})
        self.procesador.procesar()
        self.assertFalse(self.acuse("02.json")["ok"])

    def test_campos_prohibidos(self):
        for i, campo in enumerate(("estado", "intentos", "resultado", "consumo", "historial")):
            with self.subTest(campo=campo):
                self.dejar(f"{i}.json", {"op": "crear", "tareas": [self.tarea(f"T-{i}", **{campo: "hecha"})]})
                self.procesador.procesar()
                self.assertFalse(self.acuse(f"{i}.json")["ok"])
        self.assertEqual(self.reg.lista(), [])

    def test_ruta_libre_en_una_tarea(self):
        self.dejar("01.json", {"op": "crear", "tareas": [self.tarea("T-1", repo="C:\\otro\\repo")]})
        self.procesador.procesar()
        self.assertFalse(self.acuse("01.json")["ok"])

    def test_orden_por_nombre(self):
        self.dejar("b.json", {"op": "crear", "tareas": [self.tarea("T-2", dependencias=["T-1"])]})
        self.dejar("a.json", {"op": "crear", "tareas": [self.tarea("T-1")]})
        acuses = self.procesador.procesar()
        self.assertEqual([a["solicitud"] for a in acuses], ["a.json", "b.json"])
        self.assertTrue(all(a["ok"] for a in acuses))


class PruebaExplicacionYRevisa(BaseEntrada):
    def test_explicacion_valida_se_guarda(self):
        self.dejar("01.json", {"op": "crear", "tareas": [self.tarea("T-1", explicacion="Que cc pueda recibir tareas.")]})
        self.procesador.procesar()
        self.assertTrue(self.acuse("01.json")["ok"], self.acuse("01.json"))
        self.assertEqual(self.guardado("T-1")["explicacion"], "Que cc pueda recibir tareas.")

    def test_explicacion_invalida(self):
        for i, explicacion in enumerate(("x" * 301, "con\nsalto", "con\x01control", "con\ttabulador")):
            with self.subTest(explicacion=repr(explicacion[:20])):
                self.dejar(f"0{i}.json", {"op": "crear", "tareas": [self.tarea(f"T-{i}", explicacion=explicacion)]})
                self.procesador.procesar()
                self.assertFalse(self.acuse(f"0{i}.json")["ok"])
        self.assertEqual(self.reg.lista(), [])

    def test_revision_valida_agrega_dependencia(self):
        self.dejar("01.json", {"op": "crear", "tareas": [self.tarea("T-1"),
                                                         self.tarea("T-1r", revisa="T-1")]})
        self.procesador.procesar()
        self.assertTrue(self.acuse("01.json")["ok"], self.acuse("01.json"))
        t = self.guardado("T-1r")
        self.assertEqual(t["revisa"], "T-1")
        self.assertIn("T-1", t["dependencias"])
        self.assertEqual(t["estado"], "bloqueada")

    def test_revision_de_otro_cambio(self):
        self.dejar("01.json", {"op": "crear", "tareas": [self.tarea("T-1", cambio="login"),
                                                         self.tarea("T-1r", cambio="otro", revisa="T-1")]})
        self.procesador.procesar()
        self.assertFalse(self.acuse("01.json")["ok"])
        self.assertEqual(self.reg.lista(), [])

    def test_revision_inexistente_y_a_si_misma(self):
        self.dejar("01.json", {"op": "crear", "tareas": [self.tarea("T-1", revisa="T-99")]})
        self.dejar("02.json", {"op": "crear", "tareas": [self.tarea("T-2", revisa="T-2")]})
        self.procesador.procesar()
        self.assertFalse(self.acuse("01.json")["ok"])
        self.assertFalse(self.acuse("02.json")["ok"])
        self.assertEqual(self.reg.lista(), [])


class PruebaEditarCancelarReintentar(BaseEntrada):
    def crear(self, *tareas):
        self.dejar("00-crear.json", {"op": "crear", "tareas": list(tareas)})
        self.procesador.procesar()

    def test_editar_pendiente(self):
        self.crear(self.tarea("T-1"))
        self.dejar("01.json", {"op": "editar", "id": "T-1", "cambios": {"prompt": "nuevo", "prioridad": 5}})
        self.procesador.procesar()
        self.assertTrue(self.acuse("01.json")["ok"])
        t = self.guardado("T-1")
        self.assertEqual((t["prompt"], t["prioridad"]), ("nuevo", 5))

    def test_editar_agrega_dependencia_abierta(self):
        self.crear(self.tarea("T-1"), self.tarea("T-2"))
        self.dejar("01.json", {"op": "editar", "id": "T-2", "cambios": {"dependencias": ["T-1"]}})
        self.procesador.procesar()
        t = self.guardado("T-2")
        self.assertEqual(t["estado"], "bloqueada")
        self.assertEqual(t["historial"][-1]["por"], "orquestador")

    def test_editar_en_curso_se_rechaza(self):
        self.crear(self.tarea("T-1"))
        self.reg.obtener("T-1")["estado"] = "en_curso"
        self.reg.guardar()
        self.dejar("01.json", {"op": "editar", "id": "T-1", "cambios": {"prompt": "otro"}})
        self.procesador.procesar()
        acuse = self.acuse("01.json")
        self.assertFalse(acuse["ok"])
        self.assertIn("la tarea está en curso", acuse["errores"][0])

    def test_editar_campos_reservados_o_id(self):
        self.crear(self.tarea("T-1"))
        for i, cambios in enumerate(({"estado": "hecha"}, {"id": "T-9"}, {"gate": {"decision": "aprobada"}})):
            with self.subTest(cambios=cambios):
                self.dejar(f"0{i + 1}.json", {"op": "editar", "id": "T-1", "cambios": cambios})
                self.procesador.procesar()
                self.assertFalse(self.acuse(f"0{i + 1}.json")["ok"])
        self.assertEqual(self.guardado("T-1")["estado"], "pendiente")

    def test_editar_terminal_se_rechaza(self):
        self.crear(self.tarea("T-1"))
        self.reg.obtener("T-1")["estado"] = "hecha"
        self.reg.guardar()
        self.dejar("01.json", {"op": "editar", "id": "T-1", "cambios": {"prompt": "x"}})
        self.dejar("02.json", {"op": "reintentar", "id": "T-1"})
        self.procesador.procesar()
        self.assertFalse(self.acuse("01.json")["ok"])
        self.assertFalse(self.acuse("02.json")["ok"])

    def test_cancelar_en_curso(self):
        self.crear(self.tarea("T-1"))
        self.reg.obtener("T-1")["estado"] = "en_curso"
        self.reg.guardar()
        self.dejar("01.json", {"op": "cancelar", "id": "T-1"})
        self.procesador.procesar()
        t = self.guardado("T-1")
        self.assertEqual(t["cancelacion"]["por"], "cowork")

    def test_cancelar_pendiente(self):
        self.crear(self.tarea("T-1"))
        self.dejar("01.json", {"op": "cancelar", "id": "T-1"})
        self.procesador.procesar()
        self.assertEqual(self.guardado("T-1")["estado"], "cancelada")

    def test_reintentar_fallida(self):
        self.crear(self.tarea("T-1"))
        self.reg.obtener("T-1").update(estado="fallida", intentos=3)
        self.reg.guardar()
        self.dejar("01.json", {"op": "reintentar", "id": "T-1"})
        self.procesador.procesar()
        t = self.guardado("T-1")
        self.assertEqual((t["estado"], t["max_intentos"], t["historial"][-1]["por"]), ("pendiente", 4, "cowork"))

    def test_cowork_intenta_aprobar_un_gate(self):
        self.crear(self.tarea("T-1"))
        self.reg.obtener("T-1")["estado"] = "esperando_gate"
        self.reg.guardar()
        self.dejar("01.json", {"op": "aprobar", "id": "T-1"})
        self.dejar("02.json", {"op": "rechazar", "id": "T-1", "nota": "x"})
        self.procesador.procesar()
        self.assertFalse(self.acuse("01.json")["ok"])
        self.assertFalse(self.acuse("02.json")["ok"])
        self.assertEqual(self.guardado("T-1")["estado"], "esperando_gate")
        self.assertEqual(len([e for e in self.eventos if e[0] == "error" and e[1]["clase"] == "seguridad"]), 2)

    def test_solicitud_invalida_no_toca_lo_que_hay_en_memoria(self):
        self.crear(self.tarea("T-1"))
        self.reg.obtener("T-1")["prioridad"] = 7  # cambio del orquestador aún sin guardar
        self.dejar("01.json", {"op": "crear", "tareas": [self.tarea("T-1")]})  # id repetido: falla
        self.procesador.procesar()
        self.assertFalse(self.acuse("01.json")["ok"])
        self.assertEqual(self.reg.obtener("T-1")["prioridad"], 7)

    def test_operacion_desconocida(self):
        self.dejar("01.json", {"op": "borrar", "id": "T-1"})
        self.procesador.procesar()
        self.assertFalse(self.acuse("01.json")["ok"])


class PruebaEscriturasAMedias(BaseEntrada):
    def test_archivo_temporal_se_ignora(self):
        self.dejar("0007-lote.json.tmp", {"op": "crear", "tareas": [self.tarea("T-1")]})
        self.assertEqual(self.procesador.procesar(), [])
        self.assertTrue((self.carpeta_entrada / "0007-lote.json.tmp").exists())

    def test_json_incompleto_que_se_completa(self):
        self.dejar("01.json", '{"op": "crear", "tare')
        self.assertEqual(self.procesador.procesar(), [])
        self.assertTrue((self.carpeta_entrada / "01.json").exists())
        self.reloj.t += 10
        self.dejar("01.json", {"op": "crear", "tareas": [self.tarea("T-1")]})
        acuses = self.procesador.procesar()
        self.assertTrue(acuses[0]["ok"])

    def test_json_ilegible_por_60_segundos(self):
        self.dejar("01.json", "{roto")
        self.procesador.procesar()
        self.reloj.t += 59
        self.assertEqual(self.procesador.procesar(), [])
        self.reloj.t += 2
        acuses = self.procesador.procesar()
        self.assertFalse(acuses[0]["ok"])
        self.assertTrue((self.carpeta_entrada / "rechazadas" / "01.json").exists())
        self.assertFalse(self.acuse("01.json")["ok"])

    def test_json_que_no_es_objeto(self):
        self.dejar("01.json", "[1, 2]")
        acuses = self.procesador.procesar()
        self.assertFalse(acuses[0]["ok"])
        self.assertTrue((self.carpeta_entrada / "procesadas" / "01.json").exists())


class PruebaTrabajosV0(BaseEntrada):
    def test_trabajo_v0_convertido(self):
        self.dejar("t1.json", {"id": "t1", "tipo": "cc", "cambio": "login", "prompt": "Haz la tarea v0",
                               "timeout_min": 30, "nueva_sesion": True})
        self.procesador.procesar()
        acuse = self.acuse("t1.json")
        self.assertTrue(acuse["ok"], acuse)
        self.assertEqual(acuse["formato"], "v0")
        t = self.guardado("t1")
        self.assertEqual((t["agente"], t["agentes_permitidos"], t["cambio"], t["prompt"], t["estado"]),
                         ("cc", ["cc"], "login", "Haz la tarea v0", "pendiente"))
        self.assertFalse(t["gate"]["requiere"])
        self.assertEqual((t["timeout_min"], t["nueva_sesion"]), (30, True))

    def test_trabajo_v0_de_git_se_rechaza(self):
        self.dejar("g.json", {"id": "g1", "tipo": "git", "cambio": "login", "acciones": ["commit"], "mensaje": "x"})
        self.procesador.procesar()
        acuse = self.acuse("g.json")
        self.assertFalse(acuse["ok"])
        self.assertIn("Sebastian", acuse["errores"][0])
        self.assertEqual(self.reg.lista(), [])

    def test_trabajo_v0_con_repo_se_rechaza(self):
        self.dejar("r.json", {"id": "r1", "tipo": "cc", "cambio": "login", "prompt": "x", "repo": "otro"})
        self.procesador.procesar()
        acuse = self.acuse("r.json")
        self.assertFalse(acuse["ok"])
        self.assertIn("proyecto", acuse["errores"][0])

    def test_trabajo_v0_con_claves_desconocidas(self):
        self.dejar("x.json", {"id": "x1", "tipo": "cc", "cambio": "login", "prompt": "x", "otra": 1})
        self.procesador.procesar()
        self.assertFalse(self.acuse("x.json")["ok"])


if __name__ == "__main__":
    unittest.main()
