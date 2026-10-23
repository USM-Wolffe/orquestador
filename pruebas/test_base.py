"""Tarea 1.1: paquete, orq.py con sus subcomandos y bloqueo de red de las pruebas."""
from __future__ import annotations

import socket
import subprocess
import sys
import threading
import unittest

import ayudantes
from ayudantes import RAIZ_REPO, RedBloqueada


class PruebaOrqAyuda(unittest.TestCase):
    def test_help_lista_los_subcomandos(self):
        r = subprocess.run([sys.executable, str(RAIZ_REPO / "orq.py"), "--help"], capture_output=True,
                           text=True, encoding="utf-8", timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        for subcomando in ("correr", "tarea", "proyecto", "estado", "importar-v0", "instalar", "abrir"):
            self.assertIn(subcomando, r.stdout)

    def test_paquete_importable(self):
        import orquestador
        self.assertTrue(orquestador.VERSION)

    def test_cada_subcomando_responde_a_help(self):
        # Tarea 9.1: todos los comandos documentados en LEEME.md responden a --help.
        for subcomando in (["correr"], ["tarea"], ["proyecto"], ["proyecto", "nuevo"], ["proyecto", "lista"],
                           ["estado"], ["importar-v0"], ["instalar"], ["abrir"]):
            with self.subTest(subcomando=subcomando):
                r = subprocess.run([sys.executable, str(RAIZ_REPO / "orq.py"), *subcomando, "--help"],
                                   capture_output=True, text=True, encoding="utf-8", timeout=60)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("usage:", r.stdout)
                self.assertNotIn("pendiente", r.stdout.lower())


class PruebaRedBloqueada(unittest.TestCase):
    def test_ip_publica_bloqueada(self):
        with self.assertRaises(RedBloqueada):
            socket.create_connection(("192.0.2.10", 443), timeout=1)

    def test_nombre_de_host_bloqueado(self):
        with self.assertRaises(RedBloqueada):
            socket.getaddrinfo("example.com", 443)

    def test_loopback_permitido(self):
        servidor = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        servidor.bind(("127.0.0.1", 0))
        servidor.listen(1)
        puerto = servidor.getsockname()[1]
        aceptado = []
        hilo = threading.Thread(target=lambda: aceptado.append(servidor.accept()[0]))
        hilo.start()
        try:
            cliente = socket.create_connection(("127.0.0.1", puerto), timeout=5)
            cliente.close()
            hilo.join(5)
            self.assertEqual(len(aceptado), 1)
        finally:
            for s in aceptado:
                s.close()
            servidor.close()

    def test_bloqueo_activo_al_importar(self):
        self.assertIs(socket.socket.connect, ayudantes._connect)


if __name__ == "__main__":
    unittest.main()
