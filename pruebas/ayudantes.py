"""Ayudantes comunes de las pruebas del orquestador.

- Bloquean la red al importarse: solo se permite conectar a loopback (127.0.0.0/8, ::1, localhost).
- Arman una raíz de estado, una carpeta de Cowork y un perfil de usuario temporales por prueba.
- Crean repos git sintéticos (solo `git init`, sin datos reales).
Solo librería estándar.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ_REPO = Path(__file__).resolve().parent.parent
if str(RAIZ_REPO) not in sys.path:
    sys.path.insert(0, str(RAIZ_REPO))

GIT = shutil.which("git")  # solo las pruebas buscan git en el PATH; el orquestador usa la ruta de la config
FALSO = RAIZ_REPO / "pruebas" / "falsos" / "agente_falso.py"


class RedBloqueada(ConnectionRefusedError):
    """Se lanza cuando una prueba intenta salir a la red."""


_connect_original = socket.socket.connect
_connect_ex_original = socket.socket.connect_ex
_getaddrinfo_original = socket.getaddrinfo


def _es_loopback(host) -> bool:
    if host in ("localhost", "", None):
        return True
    try:
        return ipaddress.ip_address(str(host).split("%")[0]).is_loopback
    except ValueError:
        return False  # un nombre de host exigiría DNS: se bloquea


def _direccion_permitida(sock: socket.socket, direccion) -> bool:
    if getattr(socket, "AF_UNIX", None) is not None and sock.family == socket.AF_UNIX:
        return True
    host = direccion[0] if isinstance(direccion, tuple) else direccion
    return _es_loopback(host)


def _connect(self, direccion):
    if not _direccion_permitida(self, direccion):
        raise RedBloqueada(f"red bloqueada en pruebas: {direccion!r}")
    return _connect_original(self, direccion)


def _connect_ex(self, direccion):
    if not _direccion_permitida(self, direccion):
        raise RedBloqueada(f"red bloqueada en pruebas: {direccion!r}")
    return _connect_ex_original(self, direccion)


def _getaddrinfo(host, *args, **kwargs):
    if not _es_loopback(host if not isinstance(host, bytes) else host.decode()):
        raise RedBloqueada(f"resolución de nombres bloqueada en pruebas: {host!r}")
    return _getaddrinfo_original(host, *args, **kwargs)


def bloquear_red() -> None:
    socket.socket.connect = _connect
    socket.socket.connect_ex = _connect_ex
    socket.getaddrinfo = _getaddrinfo


bloquear_red()


def huella_archivo(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def foto(*carpetas: Path) -> dict:
    """Contenido y fecha de modificación de todo lo que hay bajo las carpetas (para probar 'no escribe nada')."""
    resultado = {}
    for carpeta in carpetas:
        if not carpeta.exists():
            continue
        for ruta in sorted(carpeta.rglob("*")):
            if ruta.is_file():
                resultado[str(ruta)] = (ruta.stat().st_mtime_ns, huella_archivo(ruta))
            else:
                resultado[str(ruta)] = "carpeta"
    return resultado


class ClienteTablero:
    """Cliente HTTP mínimo del tablero: solo 127.0.0.1. Guarda todas las respuestas para buscar secretos en ellas."""

    def __init__(self, puerto: int):
        self.puerto = puerto
        self.cookie: str | None = None
        self.csrf: str | None = None
        self.respuestas: list[tuple[int, dict, bytes]] = []

    def pedir(self, metodo: str, ruta: str, cuerpo=None, cabeceras: dict | None = None, cookie: bool = True):
        import http.client

        conexion = http.client.HTTPConnection("127.0.0.1", self.puerto, timeout=60)
        h = {"Host": f"127.0.0.1:{self.puerto}"}
        if cookie and self.cookie:
            h["Cookie"] = f"orq_sesion={self.cookie}"
        h.update(cabeceras or {})
        datos = None if cuerpo is None else (cuerpo if isinstance(cuerpo, bytes) else json.dumps(cuerpo).encode())
        try:
            conexion.request(metodo, ruta, body=datos, headers=h)
            r = conexion.getresponse()
            contenido = r.read()
            encabezados = {k.lower(): v for k, v in r.getheaders()}
        finally:
            conexion.close()
        self.respuestas.append((r.status, encabezados, contenido))
        return r.status, encabezados, contenido

    def json(self, ruta: str, **opciones):
        estado, _, contenido = self.pedir("GET", ruta, **opciones)
        return estado, json.loads(contenido or b"null")

    def entrar(self, enlace: str):
        ruta = enlace.split(f":{self.puerto}", 1)[1]
        estado, encabezados, _ = self.pedir("GET", ruta, cookie=False)
        galleta = encabezados.get("set-cookie", "")
        if estado == 302 and galleta.startswith("orq_sesion="):
            self.cookie = galleta.split(";", 1)[0].split("=", 1)[1]
            self.csrf = self.json("/api/sesion")[1]["csrf"]
        return estado, encabezados

    def gate(self, proyecto: str, id_tarea: str, paso: str, cuerpo: dict, csrf=True, origen=True,
             tipo: str = "application/json", cookie: bool = True):
        h = {"Content-Type": tipo}
        if origen:
            h["Origin"] = f"http://127.0.0.1:{self.puerto}" if origen is True else origen
        if csrf:
            h["X-Orq-CSRF"] = self.csrf if csrf is True else csrf
        estado, _, contenido = self.pedir("POST", f"/api/gate/{proyecto}/{id_tarea}/{paso}", cuerpo, h, cookie)
        return estado, json.loads(contenido or b"{}")


class PruebaOrq(unittest.TestCase):
    """Base: perfil de usuario, raíz de estado y carpeta de Cowork temporales en cada prueba."""

    def setUp(self) -> None:
        temporal = tempfile.TemporaryDirectory(prefix="orq-prueba-", ignore_cleanup_errors=True)
        self.addCleanup(temporal.cleanup)
        self.tmp = Path(temporal.name)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.raiz = self.home / ".orquestador"
        self.cowork = self.home / "Orquestador-Cowork"
        entorno = {
            "USERPROFILE": str(self.home),
            "APPDATA": str(self.home / "AppData" / "Roaming"),
            "LOCALAPPDATA": str(self.home / "AppData" / "Local"),
            "ProgramFiles": str(self.home / "ProgramFiles"),
            "HOME": str(self.home),
        }
        guardado = {k: os.environ.get(k) for k in [*entorno, "ORQ_RAIZ", "ORQ_CONFIG"]}

        def restaurar():
            for clave, valor in guardado.items():
                if valor is None:
                    os.environ.pop(clave, None)
                else:
                    os.environ[clave] = valor

        self.addCleanup(restaurar)
        os.environ.update(entorno)
        os.environ.pop("ORQ_RAIZ", None)
        os.environ.pop("ORQ_CONFIG", None)
        self.terminal: list[str] = []  # lo que el orquestador imprime en su terminal (con terminal=self.terminal.append)

    # --- tablero (grupo 6) ---

    def tablero(self, orq, puerto: int = 0, entrar: bool = True):
        """Levanta el tablero en un puerto libre de 127.0.0.1 y, si se pide, entra con el enlace de un solo uso."""
        from orquestador.tablero import Tablero

        tablero = Tablero(orq, puerto, terminal=self.terminal.append)
        enlace = tablero.iniciar()
        self.addCleanup(tablero.detener)
        cliente = ClienteTablero(tablero.puerto)
        if entrar:
            cliente.entrar(enlace)
        return tablero, cliente, enlace

    def bucle(self, orq, pausa: float = 0.1):
        """Corre `orq.ciclo()` en un hilo, como `orq correr` (para que el tablero reciba respuestas del bucle)."""
        import threading

        parar = threading.Event()

        def correr():
            while not parar.is_set():
                orq.ciclo()
                parar.wait(pausa)

        hilo = threading.Thread(target=correr, daemon=True)
        hilo.start()

        def detener():
            parar.set()
            hilo.join(60)

        self.addCleanup(detener)
        return detener

    def poner_tarea(self, orq, estado: str = "pendiente", proyecto: str = "demo", **datos) -> dict:
        """Deja una tarea en el registro con el estado pedido (como la habría dejado una ejecución anterior)."""
        from orquestador import registro

        ep = orq.proyectos[proyecto]
        internos = {k: datos.pop(k) for k in list(datos) if k in registro.CAMPOS_INTERNOS}
        base = {"titulo": "Tarea sintética", "prompt": "#guion: ok", "agente": "cc", "cambio": "login"}
        t = registro.construir_tarea({**base, **datos}, ep.proyecto, orq.config.agentes, "2026-10-22T10:00:00-03:00")
        t.update(estado=estado, **internos)
        t["historial"] = t.get("historial") or [{"de": None, "a": estado, "por": "cowork",
                                                 "en": "2026-10-22T10:00:00-03:00", "motivo": "creada"}]
        ep.registro.agregar(t)
        ep.registro.guardar()
        orq._publicar()
        return t

    def esperar_que(self, condicion, timeout: float = 30.0, mensaje: str = "condición") -> None:
        """Como `esperar`, pero sin llamar a `ciclo()` (cuando el bucle corre en su propio hilo)."""
        import time

        limite = time.monotonic() + timeout
        while time.monotonic() < limite:
            if condicion():
                return
            time.sleep(0.1)
        self.fail(f"se esperó {timeout} s y no se cumplió: {mensaje}")

    # --- repos y archivos sintéticos ---

    def entorno_git(self) -> dict:
        return {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_AUTHOR_NAME": "Prueba", "GIT_AUTHOR_EMAIL": "prueba@example.invalid",
                "GIT_COMMITTER_NAME": "Prueba", "GIT_COMMITTER_EMAIL": "prueba@example.invalid"}

    def crear_repo(self, nombre: str = "repo", con_commit: bool = False) -> Path:
        if not GIT:
            self.skipTest("git no está disponible para crear el repo sintético")
        repo = self.tmp / nombre
        repo.mkdir(parents=True)
        subprocess.run([GIT, "init", "-q", "-b", "main", str(repo)], check=True, env=self.entorno_git(),
                       capture_output=True)
        if con_commit:
            (repo / "README.md").write_text("Repo sintético de pruebas\n", encoding="utf-8")
            (repo / ".gitignore").write_text(".env\n", encoding="utf-8")
            for args in (["add", "."], ["commit", "-q", "-m", "inicial"]):
                subprocess.run([GIT, *args], cwd=repo, check=True, env=self.entorno_git(), capture_output=True)
        return repo

    # --- instalación con el agente falso (grupos 4 y 5) ---

    def instalar(self, config: dict | None = None, proyecto: dict | None = None) -> Path:
        """Repo con commit, config con el falso de cc y el proyecto `demo`. Devuelve el repo."""
        self.repo = self.crear_repo("demo-repo", con_commit=True)
        datos = {"agentes": {"cc": {"ejecutable": [sys.executable, str(FALSO), "--como", "cc"], "habilitado": True}},
                 "intervalo_s": 0.2}
        datos.update(config or {})
        self.escribir_config(**datos)
        self.escribir_proyecto("demo", self.repo, **({"gate_por_defecto": False} | (proyecto or {})))
        self.ruta_traza = self.tmp / "traza.jsonl"
        os.environ["ORQ_FALSO_TRAZA"] = str(self.ruta_traza)
        self.addCleanup(os.environ.pop, "ORQ_FALSO_TRAZA", None)
        return self.repo

    def orquestador(self, **opciones):
        from orquestador import inicio
        from orquestador.planificador import Orquestador

        contexto = inicio.iniciar()
        self.addCleanup(contexto.cerrar)
        opciones.setdefault("terminal", self.terminal.append)
        orq = Orquestador(contexto, **opciones)
        self.addCleanup(orq.detener)
        orq.iniciar()
        return orq

    def pedir(self, orq, *tareas, nombre: str | None = None, proyecto: str = "demo") -> None:
        """Deja un lote `crear` en la entrada de Cowork (lo procesa el próximo ciclo)."""
        carpeta = orq.proyectos[proyecto].proyecto.carpeta_cowork / "entrada"
        carpeta.mkdir(parents=True, exist_ok=True)
        PruebaOrq._n += 1
        lote = [{"titulo": f"Tarea {t['id']}", "agente": "cc", "cambio": "login", **t} for t in tareas]
        (carpeta / (nombre or f"{PruebaOrq._n:04d}.json")).write_text(
            json.dumps({"op": "crear", "tareas": lote}, ensure_ascii=False), encoding="utf-8")

    _n = 0

    def esperar(self, orq, condicion, timeout: float = 30.0, mensaje: str = "condición") -> None:
        import time

        limite = time.monotonic() + timeout
        while time.monotonic() < limite:
            orq.ciclo()
            if condicion():
                return
            time.sleep(0.2)
        self.fail(f"se esperó {timeout} s y no se cumplió: {mensaje() if callable(mensaje) else mensaje}")

    def tarea(self, orq, id_tarea: str, proyecto: str = "demo") -> dict:
        return orq.proyectos[proyecto].registro.obtener(id_tarea)

    def traza(self) -> list[dict]:
        ruta = getattr(self, "ruta_traza", None)
        if not ruta or not ruta.exists():
            return []
        return [json.loads(x) for x in ruta.read_text(encoding="utf-8").splitlines() if x.strip()]

    def lanzamientos(self) -> list[dict]:
        return [x for x in self.traza() if "argv" in x]

    def escribir_config(self, **cambios) -> Path:
        """config.json mínimo y válido; `cc` apunta al python actual como ejecutable de relleno."""
        datos = {
            "limites": {"global": 2, "por_agente": {"cc": 1}},
            "agentes": {"cc": {"ejecutable": sys.executable, "habilitado": True}},
            "herramientas": {"git": GIT or sys.executable},
            "tablero": {"puerto": 8765},
            "eventos": {"tope_mb": 10, "rotados": 5},
        }
        datos.update(cambios)
        self.raiz.mkdir(parents=True, exist_ok=True)
        ruta = self.raiz / "config.json"
        ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
        return ruta

    def escribir_proyecto(self, nombre: str, repo: Path, carpeta: str | None = None, **extra) -> Path:
        datos = {"nombre": nombre, "repo": str(repo), "base": "main", "agentes_permitidos": ["cc"]}
        datos.update(extra)
        destino = self.raiz / "proyectos" / (carpeta or nombre)
        destino.mkdir(parents=True, exist_ok=True)
        ruta = destino / "proyecto.json"
        ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
        return ruta
