"""Tarea 1.2: candado de instancia (spec proyectos, "Una sola instancia por raíz de estado")."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

from ayudantes import PruebaOrq, foto

from orquestador import candado, inicio


class PruebaCandado(PruebaOrq):
    def test_segunda_instancia_termina_sin_escribir(self):
        self.escribir_config()
        primero = inicio.iniciar()
        try:
            antes = foto(self.tmp)
            with self.assertRaises(candado.CandadoOcupado) as error:
                inicio.iniciar()
            self.assertIn("ya hay un orquestador corriendo", str(error.exception))
            self.assertEqual(foto(self.tmp), antes)
        finally:
            primero.cerrar()

    def test_cerrar_suelta_el_candado(self):
        self.escribir_config()
        inicio.iniciar().cerrar()
        self.assertFalse((self.raiz / "orquestador.lock").exists())
        inicio.iniciar().cerrar()

    def test_candado_abandonado_se_toma_y_se_registra(self):
        self.escribir_config()
        proceso = subprocess.Popen([sys.executable, "-c", "pass"])
        proceso.wait(30)
        (self.raiz / "orquestador.lock").write_text(json.dumps({"pid": proceso.pid}), encoding="utf-8")
        self.assertFalse(candado.proceso_vivo(proceso.pid))
        contexto = inicio.iniciar()
        try:
            datos = json.loads((self.raiz / "orquestador.lock").read_text(encoding="utf-8"))
            self.assertEqual(datos["pid"], os.getpid())
            self.assertIn("candado abandonado", (self.raiz / "registro.log").read_text(encoding="utf-8"))
        finally:
            contexto.cerrar()

    def test_candado_ilegible_se_trata_como_abandonado(self):
        self.escribir_config()
        (self.raiz / "orquestador.lock").write_text("basura", encoding="utf-8")
        inicio.iniciar().cerrar()

    def test_pid_reutilizado_se_trata_como_abandonado(self):
        from orquestador import procesos

        self.escribir_config()
        vivo = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self.addCleanup(lambda: (vivo.kill(), vivo.wait(10)))
        creado = procesos.hora_creacion(vivo.pid)
        self.assertIsNotNone(creado)
        candado_ruta = self.raiz / "orquestador.lock"
        candado_ruta.write_text(json.dumps({"pid": vivo.pid, "creado": creado}), encoding="utf-8")
        with self.assertRaises(candado.CandadoOcupado):
            inicio.iniciar()
        # Mismo pid, pero la hora de creación no calza: es otro proceso que reutilizó el pid.
        candado_ruta.write_text(json.dumps({"pid": vivo.pid, "creado": creado + 1}), encoding="utf-8")
        contexto = inicio.iniciar()
        try:
            datos = json.loads(candado_ruta.read_text(encoding="utf-8"))
            self.assertEqual(datos["pid"], os.getpid())
            self.assertEqual(datos["creado"], procesos.hora_creacion(os.getpid()))
        finally:
            contexto.cerrar()

    def test_proceso_vivo(self):
        self.assertTrue(candado.proceso_vivo(os.getpid()))
        self.assertFalse(candado.proceso_vivo(0))


if __name__ == "__main__":
    unittest.main()
