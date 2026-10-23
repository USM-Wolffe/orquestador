"""Tareas 4.1 a 4.3 (operacion-v1): entradas con vencimiento, terminal, `orq abrir` y Orquestador.cmd."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from ayudantes import ClienteTablero, PruebaOrq, foto  # ClienteTablero: enlace usado/vencido

import orq as cli
from orquestador import acceso
from orquestador.tablero import Entradas


class RelojFalso:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class PruebaEntradas(unittest.TestCase):
    def setUp(self):
        self.reloj = RelojFalso()
        self.entradas = Entradas(reloj=self.reloj)

    def test_canje_y_un_solo_uso(self):
        token = self.entradas.generar()
        sesion = self.entradas.canjear(token)
        self.assertIsNotNone(sesion)
        self.assertIsNone(self.entradas.canjear(token))
        self.assertIsNotNone(self.entradas.sesion(sesion))

    def test_enlace_vencido(self):
        token = self.entradas.generar()
        self.reloj.t += 301
        self.assertIsNone(self.entradas.canjear(token))
        self.assertEqual(self.entradas.abiertas, 0)

    def test_enlace_anulado_por_uno_nuevo(self):
        viejo = self.entradas.generar()
        nuevo = self.entradas.generar()
        self.assertIsNone(self.entradas.canjear(viejo))
        self.assertIsNotNone(self.entradas.canjear(nuevo))

    def test_cerrar_todas_las_sesiones(self):
        s1 = self.entradas.canjear(self.entradas.generar())
        self.assertEqual(self.entradas.cerrar_todas(), 1)
        self.assertIsNone(self.entradas.sesion(s1))


class PruebaEntradasEnElTablero(PruebaOrq):
    def test_aviso_de_sesion_nueva_sin_token(self):
        self.instalar()
        orq = self.orquestador()
        _, cliente, enlace = self.tablero(orq)
        token = enlace.split("t=", 1)[1]
        avisos = [l for l in self.terminal if "sesión nueva" in l]
        self.assertEqual(len(avisos), 1, self.terminal)
        self.assertNotIn(token, avisos[0])
        self.assertNotIn(cliente.cookie, avisos[0])
        self.assertIn("(1 abiertas)", avisos[0])

    def test_cerrar_sesiones_desde_el_tablero(self):
        self.instalar()
        orq = self.orquestador()
        tablero, cliente, _ = self.tablero(orq)
        self.assertEqual(cliente.json("/api/tareas")[0], 200)
        tablero.cerrar_sesiones()
        self.assertEqual(cliente.json("/api/tareas")[0], 401)

    def test_cookie_sin_vencimiento_propio(self):
        self.instalar()
        orq = self.orquestador()
        _, cliente, enlace = self.tablero(orq, entrar=False)
        _, encabezados = cliente.entrar(enlace)
        galleta = encabezados["set-cookie"]
        self.assertNotIn("Max-Age", galleta)
        self.assertNotIn("Expires", galleta)

    def test_entrar_usado_o_vencido_muestra_pagina_fija(self):
        self.instalar()
        orq = self.orquestador()
        _, cliente, enlace = self.tablero(orq, entrar=False)
        self.assertEqual(cliente.entrar(enlace)[0], 302)
        otro = ClienteTablero(cliente.puerto)
        estado, encabezados, cuerpo = otro.pedir("GET", enlace.split(f":{cliente.puerto}", 1)[1], cookie=False)
        self.assertEqual(estado, 401)
        self.assertIn("text/html", encabezados.get("content-type", ""))
        texto = cuerpo.decode("utf-8")
        self.assertIn(
            "Ese enlace ya se usó o venció. Si no fuiste tú, pulsa x y Enter en la ventana del orquestador "
            "para cerrar las sesiones.",
            texto)
        self.assertNotIn("{", texto)  # no es JSON


class EntradaFalsa(io.StringIO):
    def isatty(self):
        return True


class TableroFalso:
    def __init__(self):
        self.enlaces = 0
        self.cerradas = 0

    def nuevo_enlace(self):
        self.enlaces += 1
        return f"http://127.0.0.1:8765/entrar?t=falso{self.enlaces}"

    def cerrar_sesiones(self):
        self.cerradas += 1
        return 2


class PruebaTerminal(unittest.TestCase):
    def test_enter_da_enlace_y_x_cierra(self):
        tablero = TableroFalso()
        abiertos, mensajes = [], []
        acceso.escuchar_terminal(tablero, EntradaFalsa("\nx\n"), mensajes.append, abiertos.append)
        self.assertEqual(abiertos, ["http://127.0.0.1:8765/entrar?t=falso1"])
        self.assertEqual(tablero.cerradas, 1)
        self.assertIn("sesiones cerradas", " ".join(mensajes))

    def test_sin_tty_avisa_una_vez(self):
        mensajes = []
        hilo = acceso.iniciar_escucha(TableroFalso(), io.StringIO(""), mensajes.append, lambda e: None)
        self.assertIsNone(hilo)
        self.assertEqual(len(mensajes), 1)
        self.assertIn("sin terminal interactiva", mensajes[0])

    def test_ninguna_ruta_salvo_entrar_toca_tokens(self):
        ruta = Path(__file__).resolve().parent.parent / "orquestador" / "acceso.py"
        texto = ruta.read_text(encoding="utf-8")
        self.assertNotIn("CreateNamedPipe", texto)
        self.assertNotIn("NamedPipe", texto)
        self.assertNotIn("generar(", texto.replace("entradas.generar", ""))


class PruebaOrqAbrir(PruebaOrq):
    def test_abrir_con_candado_vivo(self):
        self.instalar()
        orq = self.orquestador()
        tablero, _, _ = self.tablero(orq)
        # el candado con puerto, como lo deja orq correr
        candado = json.loads((self.raiz / "orquestador.lock").read_text(encoding="utf-8"))
        candado["puerto"] = tablero.puerto
        (self.raiz / "orquestador.lock").write_text(json.dumps(candado), encoding="utf-8")
        abiertos, mensajes = [], []
        from orquestador import config as cfg
        codigo = acceso.abrir_desde_candado(cfg.cargar_config(), abiertos.append, mensajes.append)
        self.assertEqual(codigo, 0)
        self.assertEqual(abiertos, [f"http://127.0.0.1:{tablero.puerto}/"])
        self.assertIn("pulsa Enter", " ".join(mensajes))

    def test_abrir_sin_orquestador_no_abre_y_no_escribe(self):
        self.instalar()
        antes = foto(self.raiz, self.cowork)
        abiertos, mensajes = [], []
        from orquestador import config as cfg
        codigo = acceso.abrir_desde_candado(cfg.cargar_config(), abiertos.append, mensajes.append)
        self.assertEqual(codigo, 1)
        self.assertEqual(abiertos, [])
        self.assertIn("El orquestador no está corriendo", mensajes[0])
        self.assertIn("orq correr --abrir", mensajes[0])
        self.assertEqual(foto(self.raiz, self.cowork), antes)

    def test_abrir_candado_abandonado(self):
        self.instalar()
        (self.raiz / "orquestador.lock").write_text(json.dumps({"pid": 999999, "creado": None}), encoding="utf-8")
        abiertos = []
        from orquestador import config as cfg
        self.assertEqual(acceso.abrir_desde_candado(cfg.cargar_config(), abiertos.append, lambda t: None), 1)
        self.assertEqual(abiertos, [])

    def test_candado_guarda_el_puerto(self):
        from orquestador.candado import Candado
        ruta = self.tmp / "orquestador.lock"
        candado = Candado(ruta)
        candado.tomar()
        candado.fijar_puerto(8765)
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        self.assertEqual(datos["puerto"], 8765)
        candado.soltar()

    def test_correr_abrir_y_sin_tablero_no_se_combinan(self):
        import contextlib
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["correr", "--abrir", "--sin-tablero"]), 1)


class PruebaAccesoDirecto(PruebaOrq):
    def test_cmd_se_ejecuta_con_espacios_y_tildes(self):
        carpeta = self.tmp / "José Pérez" / "repo con espacios"
        carpeta.mkdir(parents=True)
        (carpeta / "orq.py").write_text(
            "import pathlib, sys\n"
            "pathlib.Path(__file__).with_name('args.txt').write_text(' '.join(sys.argv[1:]), encoding='utf-8')\n",
            encoding="utf-8")
        escritorio = self.tmp / "José Pérez" / "Desktop"
        escritorio.mkdir(parents=True)
        destino, motivo = acceso.generar_acceso_directo(escritorio, carpeta, Path(sys.executable))
        self.assertIsNone(motivo)
        self.assertTrue(destino.exists())
        texto = destino.read_text(encoding="utf-8")
        self.assertIn(acceso.MARCA_CMD, texto)
        # Windows solo: se ejecuta con cmd.exe de verdad
        r = subprocess.run(["cmd.exe", "/c", str(destino)], capture_output=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((carpeta / "args.txt").read_text(encoding="utf-8"), "correr --abrir")

    def test_rutas_con_variables_y_rechazo(self):
        contenido = acceso.contenido_acceso_directo(Path(self.home) / "work" / "orquestador", Path(sys.executable))
        self.assertIn("%USERPROFILE%", contenido)
        for malo in ("repo%malo", 'repo"malo', "repo!malo", "repo^malo", "repo\nmalo"):
            with self.subTest(malo=malo):
                destino, motivo = acceso.generar_acceso_directo(self.tmp / "esc", Path(self.tmp) / malo,
                                                                Path(sys.executable))
                self.assertIsNone(destino)
                self.assertTrue(motivo)

    def test_ruta_relativa_se_absolutiza_antes_de_revisar(self):
        # La revisión de caracteres peligrosos corre sobre la ruta absoluta, no sobre la relativa.
        repo = self.tmp / "repo_rel"
        repo.mkdir()
        (repo / "orq.py").write_text("#\n", encoding="utf-8")
        escritorio = self.tmp / "esc_rel"
        escritorio.mkdir()
        cwd = Path.cwd()
        try:
            os.chdir(self.tmp)
            destino, motivo = acceso.generar_acceso_directo(escritorio, Path("repo_rel"), Path(sys.executable))
        finally:
            os.chdir(cwd)
        self.assertIsNone(motivo)
        self.assertTrue(destino.exists())
        self.assertIn("repo_rel", destino.read_text(encoding="utf-8"))
        # Al revés: la ruta relativa se ve limpia, pero la carpeta actual trae `%` y la absoluta no es segura.
        peligrosa = self.tmp / "100%"
        (peligrosa / "repo").mkdir(parents=True)
        escritorio_malo = self.tmp / "esc_malo"
        try:
            os.chdir(peligrosa)
            destino, motivo = acceso.generar_acceso_directo(escritorio_malo, Path("repo"), Path(sys.executable))
        finally:
            os.chdir(cwd)
        self.assertIsNone(destino)
        self.assertIn("%", motivo)
        self.assertFalse((escritorio_malo / "Orquestador.cmd").exists())

    def test_no_toca_un_cmd_ajeno_ni_reescribe_el_propio(self):
        escritorio = self.tmp / "Desktop"
        escritorio.mkdir()
        ajeno = escritorio / "Orquestador.cmd"
        ajeno.write_text("@echo off\necho ajeno\n", encoding="utf-8")
        destino, motivo = acceso.generar_acceso_directo(escritorio, self.tmp / "repo", Path(sys.executable))
        self.assertIsNone(destino)
        self.assertTrue(motivo)
        self.assertEqual(ajeno.read_text(encoding="utf-8"), "@echo off\necho ajeno\n")
        ajeno.unlink()
        destino, _ = acceso.generar_acceso_directo(escritorio, self.tmp / "repo", Path(sys.executable))
        fecha = destino.stat().st_mtime_ns
        destino2, _ = acceso.generar_acceso_directo(escritorio, self.tmp / "repo", Path(sys.executable))
        self.assertEqual(destino2.stat().st_mtime_ns, fecha)

    def test_sin_inicio_automatico(self):
        # generar solo escribe el .cmd: nada en Inicio (la prueba corre en carpetas temporales)
        escritorio = self.tmp / "Desktop"
        destino, _ = acceso.generar_acceso_directo(escritorio, self.tmp / "repo", Path(sys.executable))
        self.assertEqual([p.name for p in escritorio.iterdir()], ["Orquestador.cmd"])
        texto_codigo = (Path(__file__).resolve().parent.parent / "orquestador" / "acceso.py").read_text(encoding="utf-8")
        for prohibido in ("Startup", "CurrentVersion\\Run", "schtasks", "Programador"):
            self.assertNotIn(prohibido, texto_codigo)


if __name__ == "__main__":
    unittest.main()
