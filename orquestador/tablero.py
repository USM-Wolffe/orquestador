"""Tablero (specs tablero y aprobacion-gates, design D5 y D10): un hilo de `orq correr`.

- Escucha solo en 127.0.0.1 (fijo en el código); si el puerto está ocupado, `orq correr` termina con error.
- Entrada con un enlace de un solo uso que se imprime solo en la terminal; el canje entrega una cookie de sesión
  `HttpOnly` y `SameSite=Strict`. Token, sesiones y token CSRF viven solo en memoria.
- Rechaza `Host` ajeno (rebinding de DNS) y `Origin` ajeno; responde con CSP propia, `X-Frame-Options: DENY` y sin
  cabeceras CORS.
- Solo lectura: GET y HEAD en todas las rutas; POST solo en `…/preparar` y `…/confirmar` del gate, que pasan al
  bucle en memoria. Cualquier otro método recibe 405. No escribe archivos, no lanza procesos y no corre git.
"""
from __future__ import annotations

import datetime as dt
import hmac
import json
import re
import secrets
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

import time

from . import frases, seguridad, vistas
from .estados import ESTADOS

DIRECCION = "127.0.0.1"  # fija: no es configurable (spec tablero, "Solo en 127.0.0.1")
COOKIE = "orq_sesion"
CABECERA_CSRF = "X-Orq-CSRF"
MAX_CUERPO = 16 * 1024
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; "
       "base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
ESTATICOS = Path(__file__).resolve().parent / "estaticos"
PAGINAS = {"/": ("tablero.html", "text/html; charset=utf-8"),
           "/consumo": ("consumo.html", "text/html; charset=utf-8"),
           "/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
           "/static/app.css": ("app.css", "text/css; charset=utf-8")}
VIGENCIA_TOKEN_S = 300.0
PAGINA_SIN_SESION = ("<!doctype html>\n<html lang=\"es-CL\">\n<head>\n<meta charset=\"utf-8\">\n"
                     "<title>Orquestador · entrar</title>\n<link rel=\"stylesheet\" href=\"/static/app.css\">\n"
                     "</head>\n<body>\n<main><h1>Orquestador</h1>"
                     "<p>Pulsa Enter en la ventana del orquestador para entrar</p></main>\n</body>\n</html>\n")


class Entradas:
    """Un solo token vigente, que vence a los 5 minutos y se anula al generar otro (design D8).

    Token y sesiones viven solo en memoria. El reloj es inyectable para las pruebas.
    """

    def __init__(self, reloj=time.monotonic, vigencia_s: float = VIGENCIA_TOKEN_S):
        self.reloj = reloj
        self.vigencia_s = vigencia_s
        self._token: str | None = None
        self._vence: float = 0.0
        self.sesiones: dict[str, dict] = {}
        self._lock = threading.Lock()

    def generar(self) -> str:
        with self._lock:
            self._token = secrets.token_urlsafe(32)  # al menos 32 bytes aleatorios
            self._vence = self.reloj() + self.vigencia_s
            return self._token

    def canjear(self, token: str) -> str | None:
        with self._lock:
            if not self._token or not token or self.reloj() > self._vence:
                return None
            if not hmac.compare_digest(token.encode(), self._token.encode()):
                return None
            self._token = None
            sesion = secrets.token_urlsafe(32)
            self.sesiones[sesion] = {"csrf": secrets.token_urlsafe(32), "corta": secrets.token_hex(4)}
            return sesion

    def sesion(self, valor: str | None) -> dict | None:
        if not valor:
            return None
        with self._lock:
            for clave, datos in self.sesiones.items():
                if hmac.compare_digest(clave.encode(), valor.encode()):
                    return datos
        return None

    def cerrar_todas(self) -> int:
        with self._lock:
            cantidad = len(self.sesiones)
            self.sesiones.clear()
            return cantidad

    @property
    def abiertas(self) -> int:
        with self._lock:
            return len(self.sesiones)
_NOMBRE = r"[a-z0-9][a-z0-9-]{0,60}"
_ID = r"[A-Za-z0-9][A-Za-z0-9._-]{0,100}"
RUTA_GATE = re.compile(rf"^/api/gate/({_NOMBRE})/({_ID})/(preparar|confirmar)$")
RUTA_TAREA = re.compile(rf"^/api/tareas/({_NOMBRE})/({_ID})$")
RUTA_EVENTOS = re.compile(rf"^/api/tareas/({_NOMBRE})/({_ID})/eventos$")
FECHA_OK = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ErrorTablero(Exception):
    """El tablero no pudo arrancar (por ejemplo, el puerto está ocupado)."""


class _Servidor(ThreadingHTTPServer):
    allow_reuse_address = False  # en Windows SO_REUSEADDR permitiría compartir un puerto ocupado
    daemon_threads = True

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class Tablero:
    def __init__(self, orquestador, puerto: int, terminal=None, reloj=time.monotonic):
        self.orq = orquestador
        self.puerto_pedido = puerto
        self.puerto = None
        self.terminal = terminal or orquestador.terminal
        self.entradas = Entradas(reloj=reloj)
        self._lock = threading.Lock()
        self._estaticos = {ruta: ((ESTATICOS / nombre).read_bytes(), tipo) for ruta, (nombre, tipo) in PAGINAS.items()}
        self.servidor: _Servidor | None = None
        self.hilo: threading.Thread | None = None

    # --- ciclo de vida ---

    def iniciar(self) -> str:
        try:
            self.servidor = _Servidor((DIRECCION, self.puerto_pedido), _manejador_para(self))
        except OSError as e:
            raise ErrorTablero(f"no se pudo abrir el tablero en {DIRECCION}:{self.puerto_pedido} "
                               f"(¿puerto ocupado?): {e}") from e
        self.puerto = self.servidor.server_address[1]
        self.hilo = threading.Thread(target=self.servidor.serve_forever, kwargs={"poll_interval": 0.2},
                                     name="tablero", daemon=True)
        self.hilo.start()
        return self.nuevo_enlace()

    def nuevo_enlace(self) -> str:
        """Genera un token nuevo (anula el anterior) y devuelve su enlace; el token solo va en el enlace."""
        token = self.entradas.generar()
        enlace = f"http://{DIRECCION}:{self.puerto}/entrar?t={token}"
        self.terminal(f"Tablero: abre este enlace en el navegador (sirve una sola vez): {enlace}")
        return enlace

    def detener(self) -> None:
        if self.servidor:
            self.servidor.shutdown()
            self.servidor.server_close()
            self.servidor = None

    # --- sesiones (solo en memoria) ---

    def canjear(self, token: str) -> str | None:
        sesion = self.entradas.canjear(token)
        if sesion is not None:
            hora = self.orq.reloj().strftime("%H:%M")
            self.terminal(f"[tablero] sesión nueva {hora} ({self.entradas.abiertas} abiertas)")
        return sesion

    def sesion(self, valor: str | None) -> dict | None:
        return self.entradas.sesion(valor)

    def cerrar_sesiones(self) -> int:
        return self.entradas.cerrar_todas()

    # --- datos ---

    def ahora(self) -> dt.datetime:
        return self.orq.reloj()

    def api_sesion(self, sesion: dict) -> dict:
        inst = self.orq.instantanea()
        return {"csrf": sesion["csrf"], "sesion": sesion["corta"], "estados": list(ESTADOS),
                "proyectos": sorted(inst.get("proyectos", {})), "agentes": sorted(inst.get("agentes", {})),
                "gates": {"deshabilitados": self.orq.gates.motivo_deshabilitados,
                          "aviso_integridad": self.orq.gates.aviso_integridad}}

    def api_tareas(self, consulta: dict) -> dict:
        inst = self.orq.instantanea()
        return {"momento": inst.get("momento"), "estados": list(ESTADOS),
                "tarjetas": vistas.tarjetas(inst, self.ahora(), proyecto=consulta.get("proyecto"),
                                            agente=consulta.get("agente"))}

    def _tarea(self, proyecto: str, id_tarea: str) -> dict | None:
        datos = self.orq.instantanea().get("proyectos", {}).get(proyecto)
        if not datos:
            return None
        return next((t for t in datos["tareas"] if t["id"] == id_tarea), None)

    def api_tablero(self, consulta: dict) -> dict:
        inst = self.orq.instantanea()
        diffstats, informes, eventos = {}, {}, {}
        for nombre, datos in inst.get("proyectos", {}).items():
            ep = self.orq.proyectos.get(nombre)
            if ep is None:
                continue
            lector = self.orq.lectores.get(nombre)
            for t in datos.get("tareas", []):
                diffstats[(nombre, t["id"])] = vistas.leer_diffstat(ep.proyecto.carpeta, t["id"])
                informes[(nombre, t["id"])] = vistas.leer_informe(ep.proyecto.carpeta, t["id"])
                # Solo las tareas cuyos eventos usa la vista (frase del agente y pruebas del gate): leer el registro
                # entero de cada tarea en cada sondeo de 3 s no escala.
                if lector is not None and t.get("estado") in ("en_curso", "esperando_gate"):
                    intento = len(t.get("corridas") or [])
                    eventos[(nombre, t["id"])] = [e for e in lector.desde(0, tarea=t["id"])
                                                  if e.get("intento") in (intento, None)]
        gates = {"deshabilitados": self.orq.gates.motivo_deshabilitados,
                 "aviso_integridad": self.orq.gates.aviso_integridad}
        return vistas.tablero(inst, self.ahora(), consulta.get("proyecto"), diffstats=diffstats,
                              informes=informes, eventos=eventos, gates=gates)

    def api_detalle(self, proyecto: str, id_tarea: str) -> dict | None:
        t = self._tarea(proyecto, id_tarea)
        if t is None:
            return None
        ep = self.orq.proyectos[proyecto]
        datos = vistas.detalle(ep.proyecto, t, self.orq.instantanea().get("agentes", {}), self.ahora(),
                               seguridad.niveles(t["agente"]))
        datos["explicacion"] = t.get("explicacion")
        datos["revisa"] = t.get("revisa")
        tareas = self.orq.instantanea().get("proyectos", {}).get(proyecto, {}).get("tareas", [])
        # Encabezado del panel en lenguaje simple: nada de nombres internos fuera de los detalles técnicos.
        datos["estado_texto"] = frases.texto_estacion(t, {x["id"]: x for x in tareas}, ahora=self.ahora(),
                                                      agentes=self.orq.instantanea().get("agentes", {}),
                                                      desde=vistas.desde_estado(t))
        datos["nombre_agente"] = vistas.NOMBRES_AGENTE.get(t["agente"], t["agente"])
        revisada = next((x for x in tareas if x["id"] == t.get("revisa")), None) if t.get("revisa") else None
        if revisada is not None:
            datos["explicacion"] = revisada.get("explicacion") or datos["explicacion"]
            datos["titulo_revisada"] = revisada.get("titulo")
        rev_tarea = t if t.get("revisa") else next((x for x in tareas if x.get("revisa") == id_tarea), None)
        if rev_tarea is None:
            datos["revision"] = None
        else:
            veredicto, resumen = vistas.veredicto_revision(vistas.leer_informe(ep.proyecto.carpeta, rev_tarea["id"]))
            datos["revision"] = {"veredicto": veredicto, "resumen": resumen, "agente": rev_tarea.get("agente"),
                                 "id": rev_tarea["id"]}
        return datos

    def api_eventos(self, proyecto: str, id_tarea: str, consulta: dict) -> dict | None:
        t = self._tarea(proyecto, id_tarea)
        if t is None:
            return None
        try:
            desde = int(consulta.get("desde") or 0)
        except ValueError:
            desde = 0
        intento = len(t.get("corridas") or [])
        eventos = [e for e in self.orq.lectores[proyecto].desde(desde, tarea=id_tarea)
                   if e.get("intento") in (intento, None)]
        ultimo = max([desde, *[e["seq"] for e in eventos]])
        todos = [e for e in self.orq.lectores[proyecto].desde(0, tarea=id_tarea)
                 if e.get("intento") in (intento, None)]
        return {"intento": intento, "eventos": eventos, "ultimo": ultimo,
                "frases": frases.frases_de_eventos(todos)}

    def api_consumo(self, consulta: dict) -> dict:
        desde = consulta.get("desde") if FECHA_OK.match(consulta.get("desde") or "") else None
        hasta = consulta.get("hasta") if FECHA_OK.match(consulta.get("hasta") or "") else None
        return {"agentes": vistas.consumo(self.orq.instantanea(), self.ahora(), proyecto=consulta.get("proyecto"),
                                          desde=desde, hasta=hasta)}


def _manejador_para(tablero: Tablero):
    class Manejador(BaseHTTPRequestHandler):
        server_version = "orq-tablero"
        sys_version = ""
        _cuerpo = b""

        def log_message(self, formato, *args):  # noqa: D401 - no se registra nada (la URL de entrada trae el token)
            return

        # --- respuestas ---

        def _cabeceras_comunes(self):
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")

        def _enviar(self, estado: int, cuerpo: bytes, tipo: str, extra: dict | None = None):
            self.send_response(estado)
            self._cabeceras_comunes()
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(cuerpo)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(cuerpo)

        def _json(self, estado: int, datos: dict, extra: dict | None = None):
            self._enviar(estado, json.dumps(datos, ensure_ascii=False).encode("utf-8"),
                         "application/json; charset=utf-8", extra)

        # --- métodos ---

        def do_GET(self):
            self._atender()

        def do_HEAD(self):
            self._atender()

        def do_POST(self):
            self._atender()

        def do_PUT(self):
            self._atender()

        def do_PATCH(self):
            self._atender()

        def do_DELETE(self):
            self._atender()

        def do_OPTIONS(self):
            self._atender()

        def _cookie(self) -> str | None:
            for parte in (self.headers.get("Cookie") or "").split(";"):
                nombre, _, valor = parte.strip().partition("=")
                if nombre == COOKIE:
                    return valor
            return None

        def _atender(self):
            # El cuerpo se lee siempre antes de responder: en Windows, cerrar con datos sin leer manda un RST.
            try:
                largo = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                largo = -1
            if not 0 <= largo <= MAX_CUERPO:
                self.close_connection = True
                return self._json(413, {"error": "cuerpo inválido o demasiado grande"})
            self._cuerpo = self.rfile.read(largo) if largo else b""
            ruta, _, crudo = self.path.partition("?")
            consulta = {k: v[0] for k, v in parse_qs(crudo).items()}
            puerto = tablero.puerto
            host = self.headers.get("Host", "")
            if host not in (f"127.0.0.1:{puerto}", f"localhost:{puerto}"):
                return self._json(403, {"error": "Host no permitido"})
            origen = self.headers.get("Origin")
            if origen is not None and origen != f"http://{host}":
                return self._json(403, {"error": "Origin no permitido"})
            gate = RUTA_GATE.match(ruta)
            if gate:
                if self.command != "POST":
                    return self._json(405, {"error": "método no permitido"}, {"Allow": "POST"})
            elif self.command not in ("GET", "HEAD"):
                return self._json(405, {"error": "el tablero es de solo lectura"}, {"Allow": "GET, HEAD"})
            if ruta == "/entrar":
                return self._entrar(consulta)
            if ruta in tablero._estaticos and ruta.startswith("/static/"):
                cuerpo, tipo = tablero._estaticos[ruta]
                return self._enviar(200, cuerpo, tipo)
            sesion = tablero.sesion(self._cookie())
            if sesion is None:
                if ruta == "/":
                    return self._enviar(401, PAGINA_SIN_SESION.encode("utf-8"), "text/html; charset=utf-8")
                return self._json(401, {"error": "sin sesión: usa el enlace que muestra la terminal"})
            if gate:
                return self._gate(sesion, *gate.groups())
            return self._leer(ruta, consulta, sesion)

        def _entrar(self, consulta: dict):
            if self.command == "HEAD":
                return self._enviar(200, b"", "text/plain; charset=utf-8")
            sesion = tablero.canjear(consulta.get("t") or "")
            if sesion is None:
                return self._json(401, {"error": "enlace inválido o ya usado"})
            self._enviar(302, b"", "text/plain; charset=utf-8",
                         {"Location": "/", "Set-Cookie": f"{COOKIE}={sesion}; HttpOnly; SameSite=Strict; Path=/"})

        def _leer(self, ruta: str, consulta: dict, sesion: dict):
            if ruta in tablero._estaticos:
                cuerpo, tipo = tablero._estaticos[ruta]
                return self._enviar(200, cuerpo, tipo)
            if ruta == "/api/sesion":
                return self._json(200, tablero.api_sesion(sesion))
            if ruta == "/api/tablero":
                return self._json(200, tablero.api_tablero(consulta))
            if ruta == "/api/tareas":
                return self._json(200, tablero.api_tareas(consulta))
            if ruta == "/api/consumo":
                return self._json(200, tablero.api_consumo(consulta))
            m = RUTA_TAREA.match(ruta)
            if m:
                datos = tablero.api_detalle(*m.groups())
                return self._json(200, datos) if datos else self._json(404, {"error": "no existe la tarea"})
            m = RUTA_EVENTOS.match(ruta)
            if m:
                datos = tablero.api_eventos(*m.groups(), consulta)
                return self._json(200, datos) if datos else self._json(404, {"error": "no existe la tarea"})
            return self._json(404, {"error": "no existe"})

        def _gate(self, sesion: dict, proyecto: str, id_tarea: str, paso: str):
            if self.headers.get("Origin") is None:
                return self._json(403, {"error": "falta Origin"})
            if not (self.headers.get("Content-Type") or "").lower().startswith("application/json"):
                return self._json(403, {"error": "Content-Type debe ser application/json"})
            csrf = self.headers.get(CABECERA_CSRF) or ""
            if not hmac.compare_digest(csrf.encode(), sesion["csrf"].encode()):
                return self._json(403, {"error": "falta el token CSRF o no corresponde"})
            try:
                cuerpo = json.loads(self._cuerpo.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return self._json(400, {"error": "el cuerpo no es JSON"})
            if not isinstance(cuerpo, dict):
                return self._json(400, {"error": "el cuerpo debe ser un objeto"})
            gates = tablero.orq.gates
            if paso == "preparar":
                estado, datos = gates.preparar(proyecto, id_tarea, cuerpo.get("decision"), cuerpo.get("huella"),
                                               cuerpo.get("nota"), sesion["corta"])
            else:
                estado, datos = gates.confirmar(proyecto, id_tarea, cuerpo.get("decision"), cuerpo.get("huella"),
                                                cuerpo.get("nota"), cuerpo.get("codigo"), sesion["corta"])
            return self._json(estado, datos)

    return Manejador
