"""Utilidades compartidas: fechas, escritura atómica con reintentos, expresiones de validación y registro técnico."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import time
from pathlib import Path

NOMBRE_OK = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}$")  # proyecto, cambio y rama (igual que el v0)
ID_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,100}$")  # id de tarea (igual que el v0)
BASE_OK = re.compile(r"^[A-Za-z0-9._/-]{1,80}$")

ESPERA_REEMPLAZO_S = 2.0
PAUSA_REEMPLAZO_S = 0.05


def ahora() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def marca() -> str:
    """Marca de tiempo apta para nombres de archivo, única dentro del proceso."""
    return dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def sha256(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()


def reemplazar(origen: Path, destino: Path, espera_max: float | None = None) -> None:
    """os.replace con reintentos: en Windows falla con PermissionError si un lector tiene el destino abierto."""
    limite = time.monotonic() + (ESPERA_REEMPLAZO_S if espera_max is None else espera_max)
    while True:
        try:
            os.replace(origen, destino)
            return
        except PermissionError:
            if time.monotonic() >= limite:
                raise
            time.sleep(PAUSA_REEMPLAZO_S)


def escribir_atomico(ruta: Path, contenido: bytes) -> None:
    """Escribe en `<ruta>.tmp` y reemplaza; nunca deja un archivo a medias."""
    tmp = ruta.with_name(ruta.name + ".tmp")
    with open(tmp, "wb") as f:
        f.write(contenido)
        f.flush()
        os.fsync(f.fileno())
    reemplazar(tmp, ruta)


def a_json(datos) -> bytes:
    return (json.dumps(datos, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def escribir_json(ruta: Path, datos) -> None:
    escribir_atomico(ruta, a_json(datos))


def leer_json(ruta: Path, defecto=None):
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return defecto


def normalizar(ruta: Path | str) -> str:
    return os.path.normcase(os.path.realpath(os.fspath(ruta)))


def esta_dentro(hijo: Path | str, padre: Path | str) -> bool:
    """True si `hijo` es `padre` o está dentro de él (sin distinguir mayúsculas en Windows)."""
    h, p = normalizar(hijo), normalizar(padre)
    return h == p or h.startswith(p.rstrip("\\/") + os.sep)


def registrar(raiz: Path, texto: str) -> None:
    """Agrega una línea al registro técnico de la raíz de estado."""
    raiz.mkdir(parents=True, exist_ok=True)
    with open(raiz / "registro.log", "a", encoding="utf-8") as f:
        f.write(f"{ahora()} {texto}\n")
