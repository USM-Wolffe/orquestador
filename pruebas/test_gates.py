"""Tarea 6.3: gate por botón (spec aprobacion-gates y design D5) con los ataques del design: origen ajeno, sin
CSRF, sin sesión, huella cambiada, código vencido o usado, tres códigos malos, tarea que no espera gate e integridad
del código. Todo por HTTP en 127.0.0.1 contra el tablero real; el agente es el falso de cc."""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
import unittest
from unittest import mock

from ayudantes import GIT, PruebaOrq

from orquestador import gates as gates_mod
from orquestador import integridad, worktrees

CODIGO = re.compile(r"Código para (?:aprobar|rechazar) demo/T-1 \(huella [0-9a-f]{12}\): (\d{6})")


class RelojFalso:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class BaseGate(PruebaOrq):
    def tarea_en_gate(self, **opciones):
        """T-1 corre con el falso (`ok`) y queda en `esperando_gate`; después arranca el tablero y el bucle."""
        temporal = self.tmp / "temp"
        temporal.mkdir()
        anterior = tempfile.tempdir
        tempfile.tempdir = str(temporal)
        self.addCleanup(setattr, tempfile, "tempdir", anterior)
        self.instalar(proyecto={"gate_por_defecto": True})
        opciones.setdefault("codigo_modificado", [])
        self.orq = self.orquestador(**opciones)
        self.pedir(self.orq, {"id": "T-1", "prompt": "#guion: ok"})
        self.esperar(self.orq, lambda: self.tarea(self.orq, "T-1")["estado"] == "esperando_gate", timeout=60,
                     mensaje="T-1 esperando gate")
        self.huella = self.tarea(self.orq, "T-1")["gate"]["huella"]
        self.tab, self.cliente, self.enlace = self.tablero(self.orq)
        self.bucle(self.orq)

    def codigo(self) -> str:
        encontrados = [m.group(1) for linea in self.terminal for m in [CODIGO.search(linea)] if m]
        self.assertTrue(encontrados, "la terminal no mostró el código")
        return encontrados[-1]

    def preparar(self, decision="aprobar", nota=None, huella=None):
        return self.cliente.gate("demo", "T-1", "preparar", {"decision": decision, "huella": huella or self.huella,
                                                            "nota": nota})

    def confirmar(self, codigo, decision="aprobar", nota=None, huella=None):
        return self.cliente.gate("demo", "T-1", "confirmar", {"decision": decision, "huella": huella or self.huella,
                                                             "nota": nota, "codigo": codigo})

    def eventos(self):
        ruta = self.orq.proyectos["demo"].proyecto.carpeta_eventos / "eventos.jsonl"
        return [json.loads(x) for x in ruta.read_text(encoding="utf-8").splitlines()]

    def estado_t1(self):
        return self.tarea(self.orq, "T-1")["estado"]


class PruebaFlujoCompleto(BaseGate):
    def test_aprobacion_con_codigo_de_la_terminal(self):
        self.tarea_en_gate()
        estado, datos = self.preparar()
        self.assertEqual(estado, 200, datos)
        codigo = self.codigo()
        estado, datos = self.confirmar(codigo)
        self.assertEqual((estado, datos.get("decision")), (200, "aprobada"), datos)
        # Aplicada por el bucle: tareas.json cambió y no apareció ningún archivo en decisiones\.
        t = self.tarea(self.orq, "T-1")
        self.assertEqual(t["estado"], "hecha")
        guardada = json.loads(self.orq.proyectos["demo"].proyecto.ruta_tareas.read_text(encoding="utf-8"))
        self.assertEqual(guardada["tareas"][0]["estado"], "hecha")
        self.assertEqual(list(self.orq.proyectos["demo"].proyecto.carpeta_decisiones.iterdir()), [])
        # Rastro: historial, evento, terminal y salida de Cowork.
        ultima = t["historial"][-1]
        self.assertEqual((ultima["por"], ultima["via"], ultima["huella"]), ("sebastian", "tablero", self.huella))
        self.assertRegex(ultima["sesion"], r"^[0-9a-f]{8}$")
        self.assertTrue(ultima["en"])
        gate = [e for e in self.eventos() if e["tipo"] == "gate"]
        self.assertEqual(gate[-1]["datos"]["huella"], self.huella)
        self.assertEqual(gate[-1]["datos"]["via"], "tablero")
        self.assertTrue([x for x in self.terminal if "[gate] demo/T-1 aprobada" in x and self.huella[:12] in x])
        salida = self.cowork / "demo" / "salida" / "estado.json"
        self.esperar_que(lambda: json.loads(salida.read_text(encoding="utf-8"))["tareas"][0]["gate"]["decision"]
                         == "aprobada", timeout=5, mensaje="la salida de Cowork muestra la aprobación")
        self.assertEqual(json.loads(salida.read_text(encoding="utf-8"))["tareas"][0]["gate"]["huella_corta"],
                         self.huella[:12])
        # El código ya no sirve (usado).
        self.assertEqual(self.confirmar(codigo)[0], 403)
        # El código no salió de la terminal: ni en HTTP ni en archivos de la raíz, Cowork ni el temporal.
        patron = re.compile(rf"(?<!\d){codigo}(?!\d)".encode())
        for estado, encabezados, cuerpo in self.cliente.respuestas:
            self.assertFalse(patron.search(cuerpo), "el código apareció en una respuesta HTTP")
            self.assertFalse(patron.search(json.dumps(encabezados).encode()))
        for ruta in self.tmp.rglob("*"):
            if ruta.is_file():
                self.assertFalse(patron.search(ruta.read_bytes()), f"el código apareció en {ruta}")

    def test_rechazo_exige_nota_y_vuelve_a_pendiente(self):
        self.tarea_en_gate()
        self.assertEqual(self.preparar("rechazar")[0], 400)
        self.assertEqual(self.preparar("rechazar", nota="Falta la prueba del caso borde.")[0], 200)
        estado, datos = self.confirmar(self.codigo(), "rechazar", nota="Falta la prueba del caso borde.")
        self.assertEqual((estado, datos.get("decision")), (200, "rechazada"), datos)
        rechazo = [h for h in self.tarea(self.orq, "T-1")["historial"] if h.get("motivo") == "gate rechazado"]
        self.assertEqual((rechazo[0]["de"], rechazo[0]["a"], rechazo[0]["via"]), ("esperando_gate", "pendiente", "tablero"))
        # El bucle la vuelve a lanzar con la nota de Sebastian en el prompt.
        self.esperar_que(lambda: len(self.lanzamientos()) == 2, timeout=30, mensaje="segundo lanzamiento")
        self.assertIn("Falta la prueba del caso borde.", self.lanzamientos()[1]["stdin"])


class PruebaHuellaCambiada(BaseGate):
    def test_worktree_cambio_despues_de_revisar(self):
        self.tarea_en_gate()
        self.assertEqual(self.preparar()[0], 200)
        codigo = self.codigo()
        wt = worktrees.ruta_worktree(self.orq.proyectos["demo"].proyecto, "login")
        (wt / "app.py").write_text("print('cambiado después de revisar')\n", encoding="utf-8")
        estado, datos = self.confirmar(codigo)
        self.assertEqual((estado, datos["error"]), (409, "el estado cambió, vuelve a revisar"))
        self.assertEqual(self.estado_t1(), "esperando_gate")
        (wt / "app.py").write_text("print('hola sintético')\n", encoding="utf-8")
        (wt / "nuevo.txt").write_text("archivo nuevo sin seguimiento", encoding="utf-8")
        self.assertEqual(self.preparar()[0], 409)
        self.assertEqual(self.estado_t1(), "esperando_gate")


class PruebaCodigoVencido(BaseGate):
    def test_vencido_y_usado(self):
        self.tarea_en_gate()
        reloj = RelojFalso()
        self.orq.gates.reloj = reloj
        self.assertEqual(self.preparar()[0], 200)
        codigo = self.codigo()
        reloj.t += 121
        estado, datos = self.confirmar(codigo)
        self.assertEqual((estado, datos["error"]), (403, "código vencido o ya usado"))
        self.assertEqual(self.estado_t1(), "esperando_gate")


class PruebaTresCodigosMalos(BaseGate):
    def test_bloqueo_hasta_reiniciar(self):
        self.tarea_en_gate()
        self.assertEqual(self.preparar()[0], 200)
        codigo = self.codigo()
        malo = f"{(int(codigo) + 1) % 1000000:06d}"
        for _ in range(3):
            self.assertEqual(self.confirmar(malo)[0], 403)
        estado, datos = self.confirmar(codigo)
        self.assertEqual((estado, datos["error"]), (423, "gates bloqueados hasta reiniciar"))
        self.assertEqual(self.estado_t1(), "esperando_gate")
        self.assertEqual(self.cliente.json("/api/sesion")[1]["gates"]["deshabilitados"],
                         "gates bloqueados hasta reiniciar")
        self.assertTrue([x for x in self.terminal if "bloqueados hasta reiniciar" in x])
        self.esperar_que(lambda: [e for e in self.eventos() if e["tipo"] == "error"
                                  and e["datos"]["clase"] == "seguridad"], timeout=5, mensaje="evento de seguridad")
        self.assertEqual(self.preparar()[0], 423)


class PruebaModoDesarrollo(BaseGate):
    def test_codigo_modificado_con_permiso(self):
        self.tarea_en_gate(codigo_modificado=["orquestador/tablero.py"], permitir_codigo_modificado=True)
        sesion = self.cliente.json("/api/sesion")[1]
        self.assertIn("orquestador/tablero.py", sesion["gates"]["aviso_integridad"])
        self.assertIsNone(sesion["gates"]["deshabilitados"])
        self.assertEqual(self.preparar()[0], 200)
        self.assertEqual(self.confirmar(self.codigo())[0], 200)
        self.assertIs(self.tarea(self.orq, "T-1")["historial"][-1]["codigo_modificado"], True)


class PruebaPeticionesRechazadas(PruebaOrq):
    """Ataques que se rechazan antes de llegar al bucle (no hace falta un worktree real)."""

    def setUp(self):
        super().setUp()
        espera = mock.patch.object(gates_mod, "ESPERA_BUCLE_S", 1.0)
        espera.start()
        self.addCleanup(espera.stop)
        self.instalar(proyecto={"gate_por_defecto": True})
        self.orq = self.orquestador(codigo_modificado=[])
        t = self.poner_tarea(self.orq, "esperando_gate", id="T-1", corridas=[{"intento": 1, "agente": "cc"}])
        t["gate"]["huella"] = "cd" * 32
        self.orq.proyectos["demo"].registro.guardar()
        _, self.cliente, _ = self.tablero(self.orq)
        self.cuerpo = {"decision": "aprobar", "huella": "cd" * 32, "nota": None}

    def sin_cambios(self):
        self.assertEqual(self.tarea(self.orq, "T-1")["estado"], "esperando_gate")
        self.assertEqual(self.orq.gates.cola.qsize(), 0)
        self.assertFalse([x for x in self.terminal if "Código para" in x])

    def test_origen_ajeno(self):
        estado, _ = self.cliente.gate("demo", "T-1", "preparar", self.cuerpo, origen="http://otro.example")
        self.assertEqual(estado, 403)
        self.sin_cambios()

    def test_sin_token_csrf(self):
        self.assertEqual(self.cliente.gate("demo", "T-1", "preparar", self.cuerpo, csrf=False)[0], 403)
        self.assertEqual(self.cliente.gate("demo", "T-1", "preparar", self.cuerpo, csrf="otro-token")[0], 403)
        self.sin_cambios()

    def test_sin_sesion(self):
        self.assertEqual(self.cliente.gate("demo", "T-1", "preparar", self.cuerpo, cookie=False)[0], 401)
        self.sin_cambios()

    def test_sin_origin_o_sin_json(self):
        self.assertEqual(self.cliente.gate("demo", "T-1", "preparar", self.cuerpo, origen=False)[0], 403)
        self.assertEqual(self.cliente.gate("demo", "T-1", "preparar", self.cuerpo, tipo="text/plain")[0], 403)
        self.sin_cambios()

    def test_tarea_que_no_espera_gate(self):
        self.poner_tarea(self.orq, "en_curso", id="T-2", cambio="b", corridas=[{"intento": 1, "agente": "cc"}])
        self.bucle(self.orq)
        estado, datos = self.cliente.gate("demo", "T-2", "preparar", self.cuerpo)
        self.assertEqual((estado, datos["error"]), (409, "la tarea no espera gate (está en_curso)"))
        self.assertEqual(self.tarea(self.orq, "T-2")["estado"], "en_curso")

    def test_codigo_modificado_deshabilita_los_gates(self):
        self.orq.gates.codigo_modificado = ["orquestador/planificador.py"]
        sesion = self.cliente.json("/api/sesion")[1]
        self.assertIn("orquestador/planificador.py", sesion["gates"]["aviso_integridad"])
        self.assertIn("deshabilitados", sesion["gates"]["deshabilitados"])
        self.assertEqual(self.cliente.gate("demo", "T-1", "preparar", self.cuerpo)[0], 423)
        self.sin_cambios()


class PruebaIntegridad(PruebaOrq):
    def git(self, repo, *args):
        subprocess.run([GIT, *args], cwd=repo, check=True, capture_output=True, env=self.entorno_git())

    def test_revisa_el_codigo_de_la_instalacion(self):
        repo = self.crear_repo("instalacion")
        (repo / "orquestador").mkdir()
        (repo / "orquestador" / "a.py").write_text("x = 1\n", encoding="utf-8")
        (repo / "orq.py").write_text("print('orq')\n", encoding="utf-8")
        (repo / "LEEME.md").write_text("doc\n", encoding="utf-8")
        self.git(repo, "add", ".")
        self.git(repo, "commit", "-q", "-m", "inicial")
        self.assertEqual(integridad.revisar(GIT, repo), [])
        (repo / "LEEME.md").write_text("doc cambiada\n", encoding="utf-8")  # fuera del código: no cuenta
        (repo / "orquestador" / "__pycache__").mkdir()
        (repo / "orquestador" / "__pycache__" / "a.cpython-312.pyc").write_bytes(b"\0")
        self.assertEqual(integridad.revisar(GIT, repo), [])
        (repo / "orquestador" / "a.py").write_text("x = 2\n", encoding="utf-8")
        (repo / "orquestador" / "b.py").write_text("y = 1\n", encoding="utf-8")
        self.assertEqual(sorted(integridad.revisar(GIT, repo)), ["orquestador/a.py", "orquestador/b.py"])
        sin_repo = self.tmp / "sin-repo"
        sin_repo.mkdir()
        self.assertTrue(integridad.revisar(GIT, sin_repo)[0].startswith("no se pudo verificar"))
        self.assertTrue(integridad.revisar(None, repo)[0].startswith("no se pudo verificar"))


if __name__ == "__main__":
    unittest.main()
