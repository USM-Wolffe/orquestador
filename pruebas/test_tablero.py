"""Tareas 6.1 y 6.2: tablero en 127.0.0.1, enlace de un solo uso, defensas del navegador, solo lectura, kanban,
detalle en vivo y consumo (spec tablero). Solo usa loopback."""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import unittest

from ayudantes import RAIZ_REPO, ClienteTablero, PruebaOrq, foto

from orquestador import tablero as tablero_mod


def puerto_libre() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    puerto = s.getsockname()[1]
    s.close()
    return puerto


class PruebaSoloLoopback(PruebaOrq):
    def test_direccion_de_escucha(self):
        self.instalar()
        orq = self.orquestador()
        t, _, enlace = self.tablero(orq, entrar=False)
        self.assertEqual(t.servidor.socket.getsockname()[0], "127.0.0.1")
        self.assertEqual(tablero_mod.DIRECCION, "127.0.0.1")
        self.assertTrue(enlace.startswith(f"http://127.0.0.1:{t.puerto}/entrar?t="))
        self.assertNotIn("direccion", tablero_mod.Tablero.__init__.__code__.co_varnames)  # no es configurable

    def test_puerto_ocupado(self):
        self.instalar()
        orq = self.orquestador()
        ocupado = socket.socket()
        ocupado.bind(("127.0.0.1", 0))
        ocupado.listen(1)
        self.addCleanup(ocupado.close)
        with self.assertRaises(tablero_mod.ErrorTablero):
            tablero_mod.Tablero(orq, ocupado.getsockname()[1], terminal=self.terminal.append).iniciar()


class PruebaArranque(PruebaOrq):
    """`orq correr` como subproceso: con tablero muestra el enlace; sin tablero no abre puerto; puerto ocupado falla."""

    def correr(self, *extra):
        return subprocess.run([sys.executable, str(RAIZ_REPO / "orq.py"), "correr", "--una-vez", *extra],
                              capture_output=True, text=True, encoding="utf-8", timeout=120, env=os.environ.copy())

    def test_con_y_sin_tablero(self):
        puerto = puerto_libre()
        self.instalar(config={"tablero": {"puerto": puerto}})
        r = self.correr()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, rf"http://127\.0\.0\.1:{puerto}/entrar\?t=[A-Za-z0-9_-]{{43}}")
        r = self.correr("--sin-tablero")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("/entrar?t=", r.stdout)
        self.assertNotIn("Tablero", r.stdout)

    def test_puerto_ocupado_termina_con_error(self):
        ocupado = socket.socket()
        ocupado.bind(("127.0.0.1", 0))
        ocupado.listen(1)
        self.addCleanup(ocupado.close)
        self.instalar(config={"tablero": {"puerto": ocupado.getsockname()[1]}})
        r = self.correr()
        self.assertEqual(r.returncode, 1)
        self.assertIn("puerto ocupado", r.stderr)


class PruebaEnlaceYSesion(PruebaOrq):
    def setUp(self):
        super().setUp()
        self.instalar()
        self.orq = self.orquestador()
        self.poner_tarea(self.orq, id="T-1", titulo="Tarea de prueba del tablero")

    def test_sin_sesion(self):
        _, cliente, _ = self.tablero(self.orq, entrar=False)
        estado, _, cuerpo = cliente.pedir("GET", "/api/tareas")
        self.assertEqual(estado, 401)
        self.assertNotIn(b"T-1", cuerpo)
        self.assertEqual(cliente.pedir("GET", "/")[0], 401)

    def test_canje_del_enlace(self):
        _, cliente, enlace = self.tablero(self.orq, entrar=False)
        estado, encabezados = cliente.entrar(enlace)
        self.assertEqual(estado, 302)
        self.assertEqual(encabezados["location"], "/")
        galleta = encabezados["set-cookie"]
        self.assertIn("HttpOnly", galleta)
        self.assertIn("SameSite=Strict", galleta)
        self.assertEqual(cliente.json("/api/tareas")[0], 200)
        otro = ClienteTablero(cliente.puerto)
        self.assertEqual(otro.entrar(enlace)[0], 401)  # segundo uso del mismo enlace
        self.assertIsNone(otro.cookie)

    def test_nada_en_disco(self):
        temporal = self.tmp / "temp"
        temporal.mkdir()
        anterior = tempfile.tempdir
        tempfile.tempdir = str(temporal)
        self.addCleanup(setattr, tempfile, "tempdir", anterior)
        t, cliente, enlace = self.tablero(self.orq)
        token = enlace.split("t=", 1)[1]
        for ruta in ("/", "/api/tareas", "/api/tareas/demo/T-1", "/api/consumo"):
            cliente.pedir("GET", ruta)
        self.orq.ciclo()
        secretos = [token.encode(), cliente.cookie.encode(), cliente.csrf.encode()]
        for ruta in self.tmp.rglob("*"):
            if ruta.is_file():
                contenido = ruta.read_bytes()
                for s in secretos:
                    self.assertNotIn(s, contenido, f"{ruta} contiene el token o la sesión")

    def test_reinicio(self):
        puerto = puerto_libre()
        t1, cliente, enlace = self.tablero(self.orq, puerto=puerto)
        self.assertEqual(cliente.json("/api/tareas")[0], 200)
        t1.detener()
        self.tablero(self.orq, puerto=puerto, entrar=False)
        self.assertEqual(cliente.json("/api/tareas")[0], 401)  # cookie anterior
        self.assertEqual(ClienteTablero(puerto).entrar(enlace)[0], 401)  # enlace anterior


class PruebaDefensas(PruebaOrq):
    def setUp(self):
        super().setUp()
        self.instalar()
        self.orq = self.orquestador()
        _, self.cliente, _ = self.tablero(self.orq)

    def test_rebinding_de_dns(self):
        estado, _, _ = self.cliente.pedir("GET", "/api/tareas", cabeceras={"Host": f"ataque.example:{self.cliente.puerto}"})
        self.assertEqual(estado, 403)

    def test_peticion_desde_otra_pagina(self):
        estado, _, _ = self.cliente.pedir("GET", "/api/tareas", cabeceras={"Origin": "http://otro.example"})
        self.assertEqual(estado, 403)

    def test_cabeceras(self):
        _, encabezados, _ = self.cliente.pedir("GET", "/")
        self.assertIn("default-src 'none'", encabezados["content-security-policy"])
        self.assertIn("script-src 'self'", encabezados["content-security-policy"])
        self.assertIn("frame-ancestors 'none'", encabezados["content-security-policy"])
        self.assertEqual(encabezados["x-frame-options"], "DENY")
        self.assertFalse([k for k in encabezados if k.startswith("access-control-")])

    def test_paginas_sin_scripts_en_linea(self):
        for ruta in ("/", "/consumo"):
            _, _, cuerpo = self.cliente.pedir("GET", ruta)
            self.assertNotRegex(cuerpo.decode("utf-8"), r"<script(?![^>]*\bsrc=)")
        _, _, js = self.cliente.pedir("GET", "/static/app.js")
        self.assertNotIn(b"innerHTML", js)

    def test_estaticos_sin_codigo_en_linea(self):
        # Tarea 3.1 (operacion-v1): ni scripts/estilos en línea, ni style/on*, ni fuentes externas.
        for ruta in ("/", "/consumo"):
            _, _, cuerpo = self.cliente.pedir("GET", ruta)
            html = cuerpo.decode("utf-8")
            self.assertIsNone(re.search(r"<style\b", html), ruta)
            self.assertIsNone(re.search(r"\sstyle\s*=", html), ruta)
            self.assertIsNone(re.search(r"\son\w+\s*=", html), ruta)
            self.assertNotIn("javascript:", html)
        _, _, css = self.cliente.pedir("GET", "/static/app.css")
        css_t = css.decode("utf-8")
        self.assertNotIn("@font-face", css_t)
        self.assertIsNone(re.search(r"url\(\s*['\"]?https?:", css_t))
        self.assertIn("Bahnschrift", css_t)
        self.assertIn("Segoe UI", css_t)
        html = self.cliente.pedir("GET", "/")[2].decode("utf-8")
        for texto in ("Te toca decidir", "Ahora mismo", "El plan", "Detalles técnicos"):
            self.assertIn(texto, html)
        _, _, js = self.cliente.pedir("GET", "/static/app.js")
        self.assertNotIn(b"eval", js)
        self.assertNotIn(b"new Function", js)
        self.assertIn(b"textContent", js)
        self.assertIn("Dura 2 minutos. Así nadie más puede aprobar por ti.".encode("utf-8"), js)
        self.assertIn("color-mix(in srgb,var(--color) 25%,transparent)", css_t)
        self.assertIn(".trabajando .luz", css_t)

    def test_estaticos_sin_sesion_y_pagina_401(self):
        sin = ClienteTablero(self.cliente.puerto)
        self.assertEqual(sin.pedir("GET", "/static/app.css")[0], 200)
        self.assertEqual(sin.pedir("GET", "/static/app.js")[0], 200)
        estado, _, cuerpo = sin.pedir("GET", "/")
        self.assertEqual(estado, 401)
        self.assertIn("Pulsa Enter en la ventana del orquestador para entrar", cuerpo.decode("utf-8"))
        self.assertNotIn(b"T-1", cuerpo)
        self.assertNotIn(b"demo", cuerpo)

    def test_detalle_ya_no_existe(self):
        self.assertEqual(self.cliente.pedir("GET", "/detalle?p=demo&id=T-1")[0], 404)


class PruebaSoloLectura(PruebaOrq):
    def test_bateria_de_peticiones(self):
        self.instalar()
        orq = self.orquestador()
        self.poner_tarea(orq, id="T-1")
        self.poner_tarea(orq, "esperando_gate", id="T-2", cambio="reportes")
        orq.proyectos["demo"].escritor.escribir("archivo", {"ruta": "app.py", "accion": "editar"}, tarea="T-1",
                                                intento=1, agente="cc")
        orq.ciclo()
        _, con_sesion, _ = self.tablero(orq)
        sin_sesion = ClienteTablero(con_sesion.puerto)
        rutas = ["/", "/consumo", "/static/app.js", "/static/app.css", "/api/sesion",
                 "/api/tablero", "/api/tablero?proyecto=demo",
                 "/api/tareas", "/api/tareas?proyecto=demo&agente=cc", "/api/consumo?desde=2026-10-01",
                 "/api/tareas/demo/T-1", "/api/tareas/demo/T-2", "/api/tareas/demo/T-1/eventos?desde=0",
                 "/api/tareas/demo/NO", "/entrar?t=malo", "/no-existe", "/api/gate/demo/T-2/aprobar"]
        antes = foto(self.raiz, self.cowork)
        for cliente in (con_sesion, sin_sesion):
            for ruta in rutas:
                for metodo in ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"):
                    estado, _, _ = cliente.pedir(metodo, ruta, cuerpo=b"{}" if metodo != "GET" else None,
                                                 cabeceras={"Content-Type": "application/json"})
                    if metodo not in ("GET", "HEAD"):
                        self.assertEqual(estado, 405, f"{metodo} {ruta}")
        self.assertEqual(foto(self.raiz, self.cowork), antes)
        self.assertEqual(con_sesion.pedir("POST", "/api/tareas", cuerpo=b"{}")[0], 405)


class PruebaKanbanDetalleConsumo(PruebaOrq):
    def setUp(self):
        super().setUp()
        self.instalar()
        self.otro_repo = self.crear_repo("otro-repo", con_commit=True)
        self.escribir_proyecto("otro", self.otro_repo, agentes_permitidos=["cc"])
        self.orq = self.orquestador()
        _, self.cliente, _ = self.tablero(self.orq)

    def test_filtro_por_proyecto_y_agente(self):
        self.poner_tarea(self.orq, id="T-1")
        self.poner_tarea(self.orq, id="O-1", proyecto="otro")
        _, datos = self.cliente.json("/api/tareas?proyecto=demo")
        self.assertEqual({(c["proyecto"], c["id"]) for c in datos["tarjetas"]}, {("demo", "T-1")})
        _, datos = self.cliente.json("/api/tareas")
        self.assertEqual(len(datos["tarjetas"]), 2)
        tarjeta = datos["tarjetas"][0]
        for campo in ("id", "titulo", "proyecto", "cambio", "agente", "intentos", "segundos_en_estado"):
            self.assertIn(campo, tarjeta)
        self.assertEqual(self.cliente.json("/api/tareas?agente=otro")[1]["tarjetas"], [])
        self.assertIn(b'id="f-proyecto"', self.cliente.pedir("GET", "/")[2])

    def test_agente_agotado(self):
        self.poner_tarea(self.orq, id="T-1")
        self.orq.agentes["cc"]["agotado_hasta"] = "2099-01-01T18:00:00-03:00"
        self.orq.ciclo()
        _, datos = self.cliente.json("/api/tareas")
        tarjeta = datos["tarjetas"][0]
        self.assertEqual(tarjeta["plan_agotado_hasta"], "2099-01-01T18:00:00-03:00")
        self.assertIn("plan agotado", tarjeta["motivo"])
        _, datos_tablero = self.cliente.json("/api/tablero?proyecto=demo")
        self.assertEqual(datos_tablero["agentes"][0]["estado"], "plan_agotado")
        self.assertIn(b"Plan agotado", self.cliente.pedir("GET", "/static/app.js")[2])

    def test_actividad_en_vivo(self):
        self.poner_tarea(self.orq, "en_curso", id="T-1", corridas=[{"intento": 1, "agente": "cc"}])
        _, primero = self.cliente.json("/api/tareas/demo/T-1/eventos?desde=0")
        inicio = time.monotonic()
        self.orq.proyectos["demo"].escritor.escribir("archivo", {"ruta": "src/nuevo.py", "accion": "escribir"},
                                                     tarea="T-1", intento=1, agente="cc")
        visto = None
        while time.monotonic() - inicio < 3.0 and not visto:
            _, datos = self.cliente.json(f"/api/tareas/demo/T-1/eventos?desde={primero['ultimo']}")
            visto = [e for e in datos["eventos"] if e["tipo"] == "archivo"]
            time.sleep(0.2)
        self.assertTrue(visto, "el evento no llegó en 3 s")
        self.assertEqual(visto[0]["datos"]["ruta"], "src/nuevo.py")

    def test_tarea_esperando_gate(self):
        t = self.poner_tarea(self.orq, "esperando_gate", id="T-7", corridas=[{"intento": 1, "agente": "cc"}])
        t["gate"]["huella"] = "ab" * 32
        carpeta = self.orq.proyectos["demo"].proyecto.carpeta
        (carpeta / "resultados").mkdir(exist_ok=True)
        (carpeta / "resultados" / "T-7.md").write_text("Listo: informe sintético.", encoding="utf-8")
        (carpeta / "diffstat").mkdir(exist_ok=True)
        (carpeta / "diffstat" / "T-7.json").write_text(json.dumps({"base": "main", "archivos": [
            {"ruta": "src/nuevo.py", "agregadas": 3, "borradas": 0, "nuevo": True, "binario": False}]}),
            encoding="utf-8")
        self.orq._publicar()
        _, d = self.cliente.json("/api/tareas/demo/T-7")
        self.assertTrue(d["diff_disponible"])
        self.assertEqual(d["diffstat"]["archivos"][0]["ruta"], "src/nuevo.py")
        self.assertEqual(d["informe"], "Listo: informe sintético.")
        self.assertEqual(d["gate"]["huella_corta"], "ab" * 6)
        self.assertEqual(d["niveles"]["bypass"], "duro")
        js = self.cliente.pedir("GET", "/static/app.js")[2]
        self.assertIn(b'"Aprobar"', js)
        self.assertIn('"Rechazar con un comentario"'.encode("utf-8"), js)

    def test_diff_durante_la_ejecucion(self):
        self.pedir(self.orq, {"id": "T-1", "prompt": "#guion: edita_y_espera"})
        self.esperar(self.orq, lambda: [e for e in self.orq.lectores["demo"].desde(0, tarea="T-1")
                                        if e["tipo"] == "archivo"], timeout=60, mensaje="evento archivo")
        inicio = time.monotonic()
        self.esperar(self.orq, lambda: self.cliente.json("/api/tareas/demo/T-1")[1]["diff_disponible"], timeout=10,
                     mensaje="diff stat durante la corrida")
        self.assertLessEqual(time.monotonic() - inicio, 10.0)
        d = self.cliente.json("/api/tareas/demo/T-1")[1]
        self.assertEqual(d["estado"], "en_curso")
        self.assertIn({"ruta": "src/nuevo.py", "agregadas": 2, "borradas": 0, "nuevo": True, "binario": False},
                      d["diffstat"]["archivos"])

    def test_sin_diff_calculado(self):
        self.poner_tarea(self.orq, id="T-1")
        _, d = self.cliente.json("/api/tareas/demo/T-1")
        self.assertFalse(d["diff_disponible"])
        self.assertIsNone(d["diffstat"])
        self.assertEqual(d["titulo"], "Tarea sintética")
        self.assertIn("diff no disponible", self.cliente.pedir("GET", "/")[2].decode("utf-8"))

    def test_vista_de_consumo(self):
        gasto = {"tokens_entrada": 1200, "tokens_salida": 340, "tokens_cache_lectura": 800,
                 "tokens_cache_escritura": 50, "costo_usd": 0.0421, "costo_estimado": True}
        self.poner_tarea(self.orq, "hecha", id="T-1", corridas=[
            {"intento": 1, "agente": "cc", "inicio": "2026-10-20T10:00:00-03:00", "consumo": gasto, "duracion_s": 30}])
        self.poner_tarea(self.orq, "hecha", id="T-2", cambio="b", corridas=[
            {"intento": 1, "agente": "cc", "inicio": "2026-10-21T10:00:00-03:00", "duracion_s": 12,
             "consumo": {"tokens_entrada": 10, "costo_usd": None}},
            {"intento": 2, "agente": "cc", "inicio": "2026-10-21T11:00:00-03:00", "clase_error": "limite"}])
        _, datos = self.cliente.json("/api/consumo")
        cc = datos["agentes"][0]
        self.assertEqual((cc["agente"], cc["tareas"], cc["intentos"], cc["limites"]), ("cc", 2, 3, 1))
        self.assertEqual(cc["costo_texto"], "0.0421 USD (estimado)")
        self.assertEqual(cc["tokens_entrada"], 1210)
        _, datos = self.cliente.json("/api/consumo?desde=2026-10-21&hasta=2026-10-21")
        self.assertEqual(datos["agentes"][0]["costo_texto"], "sin costo informado")
        self.assertEqual(self.cliente.json("/api/consumo?proyecto=otro")[1]["agentes"], [])


class PruebaApiTablero(PruebaOrq):
    def setUp(self):
        super().setUp()
        self.instalar()
        self.orq = self.orquestador()
        _, self.cliente, _ = self.tablero(self.orq)

    def test_api_tablero_con_gate_revisado(self):
        revisada = self.poner_tarea(self.orq, "hecha", id="T-1", titulo="Adaptador de Codex",
                                    explicacion="Que Codex reciba tareas.")
        revision = self.poner_tarea(self.orq, "esperando_gate", id="T-1r", revisa="T-1", cambio="login")
        carpeta = self.orq.proyectos["demo"].proyecto.carpeta
        (carpeta / "resultados").mkdir(exist_ok=True)
        (carpeta / "resultados" / "T-1r.md").write_text("Veredicto: con reparos\nFalta una prueba.", encoding="utf-8")
        (carpeta / "diffstat").mkdir(exist_ok=True)
        (carpeta / "diffstat" / "T-1r.json").write_text(json.dumps(
            {"base": "main", "archivos": [{"ruta": "a.py", "agregadas": 3, "borradas": 0, "nuevo": True, "binario": False}],
             "total": {"archivos": 1, "agregadas": 3, "borradas": 0}}), encoding="utf-8")
        self.orq._publicar()
        estado, datos = self.cliente.json("/api/tablero?proyecto=demo")
        self.assertEqual(estado, 200)
        self.assertEqual(datos["turno"][0]["explicacion"], "Que Codex reciba tareas.")
        self.assertEqual(datos["turno"][0]["archivos"], 1)
        self.assertEqual(datos["turno"][0]["revision"]["veredicto"], "con_reparos")
        self.assertIn("Falta una prueba", datos["turno"][0]["revision"]["resumen"])
        self.assertNotIn("PROMPT", json.dumps(datos))
        self.assertNotIn("#guion: ok", json.dumps(datos))

    def test_api_tablero_sin_sesion_401(self):
        sin = ClienteTablero(self.cliente.puerto)
        estado, _, cuerpo = sin.pedir("GET", "/api/tablero")
        self.assertEqual(estado, 401)
        self.assertNotIn(b"demo", cuerpo)

    def test_panel_en_lenguaje_simple(self):
        self.poner_tarea(self.orq, "esperando_gate", id="T-1")
        _, d = self.cliente.json("/api/tareas/demo/T-1")
        self.assertEqual(d["estado_texto"], "Te espera")
        self.assertEqual(d["nombre_agente"], "Claude Code")
        js = self.cliente.pedir("GET", "/static/app.js")[2]
        self.assertIn(b"d.estado_texto", js)
        self.assertNotIn(b"${d.estado}`", js)  # el estado interno no va en el encabezado del panel
        self.assertIn("decisiones te esperan".encode("utf-8"), js)
        self.assertIn("Nada te espera".encode("utf-8"), js)

    def test_solo_lee_eventos_de_tareas_en_curso_o_en_gate(self):
        self.poner_tarea(self.orq, "hecha", id="T-1")
        self.poner_tarea(self.orq, "esperando_gate", id="T-2")
        lector = self.orq.lectores["demo"]
        original = lector.desde
        leidas = []

        def contar(desde, tarea=None, **extra):
            leidas.append(tarea)
            return original(desde, tarea=tarea, **extra)

        lector.desde = contar
        self.addCleanup(vars(lector).pop, "desde", None)
        self.assertEqual(self.cliente.json("/api/tablero?proyecto=demo")[0], 200)
        self.assertIn("T-2", leidas)
        self.assertNotIn("T-1", leidas)

    def test_titulo_con_html_se_muestra_como_texto(self):
        self.poner_tarea(self.orq, "esperando_gate", id="T-1", titulo="<img src=x onerror=alert(1)>")
        _, datos = self.cliente.json("/api/tablero?proyecto=demo")
        self.assertEqual(datos["turno"][0]["titulo"], "<img src=x onerror=alert(1)>")
        js = self.cliente.pedir("GET", "/static/app.js")[2]
        self.assertNotIn(b"innerHTML", js)


if __name__ == "__main__":
    unittest.main()
