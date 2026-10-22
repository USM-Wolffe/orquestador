"""Tarea 2.1: registro de tareas (spec registro-tareas: "Registro JSON por proyecto con un solo escritor" y
"Campos mínimos de una tarea")."""
from __future__ import annotations

import json
import os
import threading
import time
import unittest
from unittest import mock

from ayudantes import PruebaOrq

from orquestador import comun, registro
from orquestador import config as cfg
from orquestador import proyectos as proy

MOMENTO = "2026-10-22T10:00:00-03:00"


class BaseRegistro(PruebaOrq):
    def setUp(self):
        super().setUp()
        self.repo = self.crear_repo()
        self.escribir_config()
        self.escribir_proyecto("demo", self.repo, red={"permitida": False})
        self.config = cfg.cargar_config()
        self.proyecto = proy.cargar_proyectos(self.config)[0]
        self.proyecto.carpeta.mkdir(parents=True, exist_ok=True)

    def tarea(self, **datos):
        base = {"id": "T-1", "titulo": "Prueba", "prompt": "Haz algo sintético", "agente": "cc", "cambio": "login"}
        base.update(datos)
        return registro.construir_tarea(base, self.proyecto, self.config.agentes, MOMENTO)


class PruebaCamposMinimos(BaseRegistro):
    def test_tarea_creada_con_lo_minimo(self):
        t = self.tarea()
        self.assertEqual(t["agentes_permitidos"], ["cc"])
        self.assertEqual(t["dependencias"], [])
        self.assertEqual(t["rama"], "login")
        self.assertEqual(t["gate"]["requiere"], True)  # gate_por_defecto del proyecto
        self.assertIsNone(t["gate"]["decision"])
        self.assertEqual((t["intentos"], t["max_intentos"]), (0, 3))
        self.assertEqual((t["creada"], t["actualizada"]), (MOMENTO, MOMENTO))
        self.assertIsNone(t["iniciada"])
        self.assertIsNone(t["terminada"])
        self.assertEqual(t["historial"], [])
        for campo in ("id", "titulo", "prompt", "agente", "agentes_permitidos", "estado", "dependencias", "cambio",
                      "rama", "gate", "intentos", "max_intentos", "resultado", "consumo", "creada", "actualizada",
                      "iniciada", "terminada", "historial"):
            self.assertIn(campo, t)

    def test_gate_por_defecto_del_proyecto(self):
        self.proyecto.gate_por_defecto = False
        self.assertFalse(self.tarea()["gate"]["requiere"])
        self.assertTrue(self.tarea(gate={"requiere": True, "motivo": "revisar"})["gate"]["requiere"])

    def test_opcionales_validos(self):
        t = self.tarea(base="develop", red=False, prioridad=10, nueva_sesion=True, timeout_min=30,
                       no_antes_de="2026-10-22T18:00:00-03:00", dependencias=["T-0"])
        self.assertEqual((t["base"], t["prioridad"], t["timeout_min"]), ("develop", 10, 30))

    def test_agente_no_permitido(self):
        for datos in ({"agente": "codex"}, {"agente": "cc", "agentes_permitidos": ["cc", "codex"]}):
            with self.subTest(datos=datos), self.assertRaises(registro.ErrorValidacion):
                self.tarea(**datos)
        self.config.agentes["cc"].habilitado = False
        with self.assertRaises(registro.ErrorValidacion):
            self.tarea()

    def test_campos_obligatorios_y_formatos(self):
        casos = [{"id": ""}, {"id": "con espacio"}, {"titulo": ""}, {"prompt": "  "}, {"cambio": "Login"},
                 {"rama": "rama mala"}, {"base": "a b"}, {"red": "si"}, {"prioridad": "alta"},
                 {"timeout_min": 0}, {"no_antes_de": "mañana"}, {"dependencias": ["T-1"]},
                 {"dependencias": "T-0"}, {"gate": {"requiere": True, "decision": "aprobada"}}]
        for datos in casos:
            with self.subTest(datos=datos), self.assertRaises(registro.ErrorValidacion):
                self.tarea(**datos)

    def test_campos_reservados_y_desconocidos(self):
        for campo in ("estado", "intentos", "resultado", "consumo", "historial", "repo", "worktree"):
            with self.subTest(campo=campo), self.assertRaises(registro.ErrorValidacion) as e:
                self.tarea(**{campo: "x"})
            self.assertIn(campo, str(e.exception))

    def test_red_sin_permiso_del_proyecto(self):
        with self.assertRaises(registro.ErrorValidacion):
            self.tarea(red=True)
        self.proyecto.red_permitida = True
        self.assertTrue(self.tarea(red=True)["red"])


class PruebaEscrituraAtomica(BaseRegistro):
    def nuevo_registro(self):
        r = registro.Registro(self.proyecto.ruta_tareas)
        r.cargar()
        return r

    def test_escritura_atomica_con_bak(self):
        r = self.nuevo_registro()
        r.agregar(dict(self.tarea(), estado="pendiente"))
        r.guardar()
        primera = self.proyecto.ruta_tareas.read_bytes()
        self.assertFalse(self.proyecto.ruta_tareas.with_name("tareas.json.bak").exists())
        r.obtener("T-1")["estado"] = "en_curso"
        r.guardar()
        self.assertEqual(self.proyecto.ruta_tareas.with_name("tareas.json.bak").read_bytes(), primera)
        datos = json.loads(self.proyecto.ruta_tareas.read_text(encoding="utf-8"))
        self.assertEqual(datos["tareas"][0]["estado"], "en_curso")
        self.assertFalse(self.proyecto.ruta_tareas.with_name("tareas.json.tmp").exists())

    def test_se_escribe_primero_el_temporal(self):
        r = self.nuevo_registro()
        r.agregar(dict(self.tarea(), estado="pendiente"))
        llamados = []
        original = comun.os.replace

        def espia(origen, destino):
            llamados.append((os.path.basename(origen), os.path.basename(destino)))
            return original(origen, destino)

        with mock.patch.object(comun.os, "replace", side_effect=espia):
            r.guardar()
        self.assertIn(("tareas.json.tmp", "tareas.json"), llamados)

    def test_registro_corrupto_usa_la_copia(self):
        r = self.nuevo_registro()
        r.agregar(dict(self.tarea(), estado="pendiente"))
        r.guardar()
        r.obtener("T-1")["estado"] = "en_curso"
        r.guardar()  # ahora .bak tiene la versión 'pendiente'
        self.proyecto.ruta_tareas.write_text("{roto", encoding="utf-8")
        r2 = registro.Registro(self.proyecto.ruta_tareas)
        avisos = r2.cargar()
        self.assertEqual(r2.obtener("T-1")["estado"], "pendiente")
        danados = list(self.proyecto.carpeta.glob("tareas.json.danado-*"))
        self.assertEqual(len(danados), 1)
        self.assertEqual(danados[0].read_text(encoding="utf-8"), "{roto")
        self.assertTrue(any("dañado" in a for a in avisos))

    def test_registro_y_copia_corruptos(self):
        self.proyecto.ruta_tareas.write_text("{roto", encoding="utf-8")
        self.proyecto.ruta_tareas.with_name("tareas.json.bak").write_text("tampoco", encoding="utf-8")
        with self.assertRaises(registro.ErrorRegistro):
            registro.Registro(self.proyecto.ruta_tareas).cargar()

    def test_reemplazo_con_reintentos(self):
        r = self.nuevo_registro()
        r.agregar(dict(self.tarea(), estado="pendiente"))
        original = comun.os.replace
        fallas = {"n": 0}

        def falla_dos_veces(origen, destino):
            if os.path.basename(destino) == "tareas.json" and fallas["n"] < 2:
                fallas["n"] += 1
                raise PermissionError(13, "archivo abierto por un lector")
            return original(origen, destino)

        with mock.patch.object(comun.os, "replace", side_effect=falla_dos_veces):
            r.guardar()
        self.assertEqual(fallas["n"], 2)
        self.assertEqual(json.loads(self.proyecto.ruta_tareas.read_text(encoding="utf-8"))["tareas"][0]["id"], "T-1")

    def test_reemplazo_que_nunca_se_libera_falla_sin_perder_el_cambio(self):
        r = self.nuevo_registro()
        r.agregar(dict(self.tarea(), estado="pendiente"))
        with mock.patch.object(comun, "ESPERA_REEMPLAZO_S", 0.2), \
                mock.patch.object(comun.os, "replace", side_effect=PermissionError(13, "bloqueado")):
            with self.assertRaises(PermissionError):
                r.guardar()
        self.assertEqual(r.obtener("T-1")["estado"], "pendiente")  # el cambio sigue en memoria
        r.guardar()  # y se escribe en cuanto el archivo se libera
        self.assertTrue(self.proyecto.ruta_tareas.exists())

    @unittest.skipUnless(os.name == "nt", "el bloqueo de archivos abiertos es propio de Windows")
    def test_lector_real_con_el_archivo_abierto(self):
        r = self.nuevo_registro()
        r.agregar(dict(self.tarea(), estado="pendiente"))
        r.guardar()
        lector = open(self.proyecto.ruta_tareas, "rb")
        threading.Timer(0.4, lector.close).start()
        inicio = time.monotonic()
        r.obtener("T-1")["estado"] = "en_curso"
        r.guardar()
        self.assertGreaterEqual(time.monotonic() - inicio, 0.3)
        self.assertIn("en_curso", self.proyecto.ruta_tareas.read_text(encoding="utf-8"))

    def test_escritura_externa_detectada(self):
        r = self.nuevo_registro()
        r.agregar(dict(self.tarea(), estado="pendiente"))
        r.guardar()
        ajeno = self.proyecto.ruta_tareas.read_text(encoding="utf-8").replace("pendiente", "hecha")
        self.proyecto.ruta_tareas.write_text(ajeno, encoding="utf-8")
        self.assertTrue(r.revisar_externo())
        r.obtener("T-1")["prioridad"] = 5
        avisos = r.guardar()
        externos = list(self.proyecto.carpeta.glob("tareas.json.externo-*"))
        self.assertEqual(len(externos), 1)
        self.assertEqual(externos[0].read_text(encoding="utf-8"), ajeno)
        datos = json.loads(self.proyecto.ruta_tareas.read_text(encoding="utf-8"))
        self.assertEqual(datos["tareas"][0]["estado"], "pendiente")
        self.assertTrue(any("externa" in a for a in avisos))

    def test_estado_separado_por_proyecto(self):
        r = self.nuevo_registro()
        r.agregar(dict(self.tarea(), estado="pendiente"))
        r.guardar()
        self.assertTrue((self.raiz / "proyectos" / "demo" / "tareas.json").is_file())

    def test_id_repetido_en_el_registro(self):
        r = self.nuevo_registro()
        r.agregar(dict(self.tarea(), estado="pendiente"))
        with self.assertRaises(registro.ErrorValidacion):
            r.agregar(dict(self.tarea(), estado="pendiente"))


if __name__ == "__main__":
    unittest.main()
