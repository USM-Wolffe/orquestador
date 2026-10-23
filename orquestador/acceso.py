"""Acceso fácil al tablero (design D8 y D9, spec acceso-tablero).

- Enter en la ventana del orquestador da un enlace nuevo y abre el navegador; `x` y Enter cierra las sesiones.
  Es la única vía para pedir un enlace: este módulo no crea tuberías, archivos ni rutas que entreguen tokens.
- `orq abrir` solo lee el candado y abre `/` sin token.
- Generador del acceso directo `Orquestador.cmd` (lo usa `orq instalar`, tarea 5.x de la parte D).
"""
from __future__ import annotations

import ctypes
import json
import os
import sys
import threading
import webbrowser
from pathlib import Path

from .procesos import proceso_vivo

MARCA_CMD = "rem orq-acceso-directo v1 (lo genera orq instalar; no lo edites a mano)"
CARACTERES_PELIGROSOS = ('%', '"', "!", "^", "\n", "\r")


# --- terminal del orquestador ---

def escuchar_terminal(tablero, entrada, terminal=print, abrir=None) -> None:
    """Lee líneas de la terminal: Enter → enlace nuevo y navegador; `x` → cierra todas las sesiones."""
    abrir = abrir or webbrowser.open
    for linea in entrada:
        orden = linea.strip().lower()
        if orden == "x":
            cerradas = tablero.cerrar_sesiones()
            terminal(f"[tablero] sesiones cerradas ({cerradas} cerradas)")
        elif orden == "":
            enlace = tablero.nuevo_enlace()
            abrir(enlace)


def iniciar_escucha(tablero, entrada=None, terminal=print, abrir=None) -> threading.Thread | None:
    """Arranca el hilo de la terminal solo si la entrada estándar es un TTY; si no, avisa una vez."""
    entrada = sys.stdin if entrada is None else entrada
    es_tty = False
    try:
        es_tty = bool(entrada is not None and entrada.isatty())
    except (OSError, ValueError):
        es_tty = False
    if not es_tty:
        terminal("[tablero] sin terminal interactiva: no se generarán enlaces nuevos con Enter")
        return None
    hilo = threading.Thread(target=escuchar_terminal, kwargs={"tablero": tablero, "entrada": entrada,
                                                              "terminal": terminal, "abrir": abrir},
                            name="acceso-terminal", daemon=True)
    hilo.start()
    return hilo


# --- orq abrir ---

def abrir_desde_candado(config, abrir=None, terminal=print) -> int:
    """Abre `/` sin token si el orquestador corre según el candado. No escribe nada y nunca toca un token."""
    abrir = abrir or webbrowser.open
    ruta = config.raiz / "orquestador.lock"
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        pid, creado = int(datos.get("pid")), datos.get("creado")
        puerto = int(datos.get("puerto") or config.puerto)
    except (OSError, ValueError, TypeError, AttributeError):
        pid, creado, puerto = None, None, config.puerto
    if pid is None or not proceso_vivo(pid, creado):
        terminal("El orquestador no está corriendo: usa el acceso directo o `orq correr --abrir`")
        return 1
    abrir(f"http://127.0.0.1:{puerto}/")
    terminal("Si el tablero pide entrar, pulsa Enter en la ventana del orquestador.")
    return 0


# --- acceso directo Orquestador.cmd ---

def _ruta_para_cmd(ruta) -> str:
    # La revisión de caracteres peligrosos va DESPUÉS de abspath: una ruta relativa puede verse rara
    # y quedar limpia al absolutizarse (o al revés).
    absoluta = os.path.abspath(str(Path(ruta)))
    for caracter in CARACTERES_PELIGROSOS:
        if caracter in absoluta:
            raise ValueError(f"la ruta no se puede escribir con seguridad en un .cmd (trae {caracter!r}): {absoluta}")
    entorno = os.environ
    # LOCALAPPDATA va primero: también queda bajo USERPROFILE y la plantilla usa la variable más específica.
    for variable in ("LOCALAPPDATA", "USERPROFILE"):
        base = entorno.get(variable)
        if base:
            base_abs = os.path.abspath(base)
            if os.path.normcase(absoluta) == os.path.normcase(base_abs) or \
                    os.path.normcase(absoluta).startswith(os.path.normcase(base_abs).rstrip("\\/") + os.sep):
                resto = absoluta[len(base_abs):].lstrip("\\/")
                return f"%{variable}%\\{resto}" if resto else f"%{variable}%"
    return absoluta


def contenido_acceso_directo(repo, python_exe) -> str:
    """Texto del `.cmd` (con marca). Rechaza rutas con `%`, comillas, `!`, `^` o saltos de línea."""
    repo_cmd = _ruta_para_cmd(repo)
    python_cmd = _ruta_para_cmd(python_exe)
    lineas = ["@echo off", MARCA_CMD, "chcp 65001 >nul", "title Orquestador",
              f"cd /d \"{repo_cmd}\"", f"\"{python_cmd}\" \"{repo_cmd}\\orq.py\" correr --abrir",
              "if errorlevel 1 pause"]
    return "\r\n".join(lineas) + "\r\n"


def _bytes_cmd(contenido: str) -> bytes:
    try:
        return contenido.encode("ascii")
    except UnicodeEncodeError:
        return contenido.encode("utf-8")  # sin BOM; el chcp 65001 va antes de cualquier ruta


def generar_acceso_directo(escritorio, repo, python_exe) -> tuple[Path | None, str | None]:
    """Genera `Orquestador.cmd` en el escritorio. Devuelve (ruta, None) o (None, motivo) sin tocar nada ajeno."""
    try:
        contenido = contenido_acceso_directo(repo, python_exe)
    except ValueError as e:
        return None, str(e)
    destino = Path(escritorio) / "Orquestador.cmd"
    datos = _bytes_cmd(contenido)
    if destino.exists():
        actual = destino.read_bytes()
        if MARCA_CMD.encode("ascii") not in actual:
            return None, f"ya existe {destino} y no lo generó el orquestador; no se tocó"
        if actual == datos:
            return destino, None  # idempotente: ni el contenido ni la fecha cambian
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(datos)
    return destino, None


def escritorio_real() -> Path:
    """Carpeta real del escritorio con SHGetKnownFolderPath (puede estar en OneDrive); respaldo: %USERPROFILE%\\Desktop."""
    try:
        if sys.platform == "win32":
            class _Guid(ctypes.Structure):
                _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort), ("Data3", ctypes.c_ushort),
                            ("Data4", ctypes.c_ubyte * 8)]

            carpeta_id = _Guid(0xB4BFCC3A, 0xDB2C, 0x424C,
                               (ctypes.c_ubyte * 8)(0xB0, 0x29, 0x7F, 0xE9, 0x9A, 0x87, 0xC6, 0x41))
            salida = ctypes.c_wchar_p()
            if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(carpeta_id), 0, None,
                                                          ctypes.byref(salida)) == 0 and salida.value:
                ruta = Path(salida.value)
                ctypes.windll.ole32.CoTaskMemFree(salida)
                return ruta
    except (OSError, AttributeError, ValueError):
        pass
    return Path(os.environ.get("USERPROFILE") or Path.home()) / "Desktop"
