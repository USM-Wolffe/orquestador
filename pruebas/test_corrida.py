"""Tarea 4.2: lanzador común (sin ventana, Job Object, tiempo máximo, cancelación con hijos, orquestador que
muere) y un adaptador mínimo que usa el mismo ciclo (specs adaptadores-agente y planificacion-ejecucion)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path

from ayudantes import FALSO, RAIZ_REPO

from orquestador import procesos
from orquestador.adaptadores.base import EstadoLectura, Lanzamiento, Resultado
from orquestador.adaptadores.cc import AdaptadorCC
from orquestador.config import Agente
from orquestador.corrida import OpcionesCorrida, correr
from orquestador.eventos import EscritorEventos


def esperar_muerto(pid: int, segundos: float = 10.0) -> bool:
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if not procesos.proceso_vivo(pid):
            return True
        time.sleep(0.1)
    return False


class AdaptadorMinimo:
    """Adaptador de prueba distinto de cc: el núcleo lo corre sin cambios."""
    nombre = "minimo"
    banderas_prohibidas = ()
    valores_prohibidos = {}

    def normalizar(self, linea, estado):
        return [("mensaje", {"texto": linea["texto"]})] if linea.get("tipo") == "mensaje" else []

    def cierre(self, estado, codigo, stderr, duracion_s):
        return Resultado(ok=codigo == 0, texto="hecho", codigo_salida=codigo, duracion_s=duracion_s)


class BaseCorrida(unittest.TestCase):
    def setUp(self):
        temporal = tempfile.TemporaryDirectory(prefix="orq-corrida-", ignore_cleanup_errors=True)
        self.addCleanup(temporal.cleanup)
        self.tmp = Path(temporal.name)
        self.escritor = EscritorEventos(self.tmp / "eventos", "demo")
        self.traza = self.tmp / "traza.jsonl"
        self.cc = AdaptadorCC(Agente("cc", [sys.executable, str(FALSO), "--como", "cc"], True, True))
        self.pids = []

    def lanzamiento_cc(self, guion: str) -> Lanzamiento:
        argv = [sys.executable, str(FALSO), "--como", "cc", "-p", "--output-format", "stream-json", "--verbose",
                "--session-id", str(uuid.uuid4())]
        return Lanzamiento(argv=argv, env={**os.environ, "ORQ_FALSO_TRAZA": str(self.traza)}, cwd=self.tmp,
                           stdin=f"#guion: {guion}\n")

    def opciones(self, **extra) -> OpcionesCorrida:
        return OpcionesCorrida(timeout_s=extra.pop("timeout_s", 60), al_lanzar=lambda pid, c: self.pids.append(pid),
                               **extra)

    def eventos(self):
        return [json.loads(x) for x in (self.tmp / "eventos" / "eventos.jsonl").read_text(encoding="utf-8").splitlines()]


class PruebaCicloComun(BaseCorrida):
    def test_adaptador_minimo_con_el_mismo_ciclo(self):
        script = "import json; print(json.dumps({'tipo': 'mensaje', 'texto': 'hola'})); print('no es json')"
        lanz = Lanzamiento(argv=[sys.executable, "-c", script], env=dict(os.environ), cwd=self.tmp, stdin=None)
        estado = EstadoLectura(worktree=self.tmp)
        r = correr(AdaptadorMinimo(), lanz, estado, self.escritor, "T-1", 1, self.opciones())
        self.assertTrue(r.ok)
        self.assertEqual([e["tipo"] for e in self.eventos()], ["mensaje", "fin"])
        self.assertEqual(estado.lineas_no_json, 1)
        self.assertEqual(len(self.pids), 1)


class PruebaTiempoYCancelacion(BaseCorrida):
    def test_se_acaba_el_tiempo(self):
        r = correr(self.cc, self.lanzamiento_cc("colgado"), EstadoLectura(worktree=self.tmp), self.escritor, "T-1",
                   1, self.opciones(timeout_s=1.5))
        self.assertFalse(r.ok)
        self.assertEqual(r.error["clase"], "timeout")
        self.assertTrue(esperar_muerto(self.pids[0]))
        tipos = [(e["tipo"], e["datos"].get("clase")) for e in self.eventos()]
        self.assertIn(("error", "timeout"), tipos)
        self.assertEqual(tipos[-1][0], "fin")

    def test_cancelacion_con_hijos(self):
        cancelar = threading.Event()
        salida = {}
        hilo = threading.Thread(target=lambda: salida.update(r=correr(
            self.cc, self.lanzamiento_cc("hijo_largo"), EstadoLectura(worktree=self.tmp), self.escritor, "T-1", 1,
            self.opciones(cancelar=cancelar))))
        hilo.start()
        limite = time.monotonic() + 20
        hijo = None
        while time.monotonic() < limite and hijo is None:
            if self.traza.exists():
                hijo = next((json.loads(x)["hijo"] for x in self.traza.read_text(encoding="utf-8").splitlines()
                             if '"hijo"' in x), None)
            time.sleep(0.1)
        self.assertIsNotNone(hijo, "el falso no lanzó su proceso hijo")
        self.assertTrue(procesos.proceso_vivo(hijo))
        cancelar.set()
        hilo.join(30)
        self.assertEqual(salida["r"].error["clase"], "cancelada")
        self.assertTrue(esperar_muerto(self.pids[0]), "el agente sigue vivo")
        self.assertTrue(esperar_muerto(hijo), "el hijo del agente sigue vivo")


@unittest.skipUnless(os.name == "nt", "los Job Objects son de Windows")
class PruebaOrquestadorMuere(unittest.TestCase):
    def test_el_orquestador_muere_y_mueren_sus_agentes(self):
        mini = subprocess.Popen([sys.executable, str(RAIZ_REPO / "pruebas" / "falsos" / "orquestador_mini.py"),
                                 str(FALSO)], stdout=subprocess.PIPE, text=True)
        try:
            pid_agente = int(mini.stdout.readline().strip())
            self.assertTrue(procesos.proceso_vivo(pid_agente))
            mini.kill()  # muere de golpe, sin limpiar nada
            mini.wait(10)
            self.assertTrue(esperar_muerto(pid_agente), "el agente sobrevivió al orquestador")
        finally:
            if mini.poll() is None:
                mini.kill()
                mini.wait(10)
            mini.stdout.close()


if __name__ == "__main__":
    unittest.main()
