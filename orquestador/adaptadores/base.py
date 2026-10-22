"""Interfaz común de los adaptadores de agente (spec adaptadores-agente)."""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ..procesos import CREATE_NO_WINDOW


@dataclass
class ContextoLanzamiento:
    tarea: dict
    proyecto: object
    config: object
    worktree: Path
    sesion: str
    retomar: bool
    carpeta_corrida: Path
    entorno: dict[str, str]  # ya filtrado por seguridad.entorno_filtrado
    prompt: str


@dataclass
class Lanzamiento:
    argv: list[str]
    env: dict[str, str]
    cwd: Path
    stdin: str | None
    archivos: dict[Path, bytes] = field(default_factory=dict)  # se escriben antes de lanzar (p. ej. el perfil)
    herramientas_esperadas: tuple[str, ...] = ()


@dataclass
class Limite:
    hasta: str | None  # ISO 8601 con zona, o None si el agente no dijo la hora
    texto: str


@dataclass
class EstadoLectura:
    worktree: Path
    retomada: bool = False
    sesion: str | None = None
    modelo: str | None = None
    resultado: dict | None = None
    pendientes: dict = field(default_factory=dict)  # tool_use_id → (nombre, entrada)
    limite_hasta: str | None = None
    limite_visto: bool = False
    lineas_no_json: int = 0


@dataclass
class Resultado:
    ok: bool
    texto: str = ""
    codigo_salida: int | None = None
    duracion_s: float = 0.0
    sesion: str | None = None
    modelo: str | None = None
    consumo: dict = field(default_factory=dict)
    negaciones: list = field(default_factory=list)
    error: dict | None = None  # {"clase": ..., "mensaje": ...}
    limite: Limite | None = None
    sesion_inexistente: bool = False


IGNORADO = "_ignorado"  # marca que devuelve normalizar() para un evento del agente que no conoce


class Adaptador(Protocol):
    nombre: str
    version_minima: str
    version_verificada: str
    banderas_prohibidas: tuple[str, ...]
    valores_prohibidos: dict[str, tuple[str, ...]]  # las capas obligatorias las fija seguridad.CAPAS_OBLIGATORIAS

    def lanzamiento(self, ctx: ContextoLanzamiento) -> Lanzamiento: ...

    def normalizar(self, linea: dict, estado: EstadoLectura) -> list[tuple[str, dict]]: ...

    def cierre(self, estado: EstadoLectura, codigo: int | None, stderr: str, duracion_s: float) -> Resultado: ...


def version_de(texto: str) -> tuple[int, int, int] | None:
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", texto or "")
    return tuple(int(x) for x in m.groups()) if m else None


def verificar_version(adaptador: Adaptador, ejecutable: list[str], entorno: dict[str, str],
                      timeout_s: float = 10.0) -> dict:
    """Corre `<agente> --version` y decide si el agente queda disponible (spec adaptadores-agente)."""
    try:
        r = subprocess.run([*ejecutable, "--version"], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout_s, env=entorno, stdin=subprocess.DEVNULL,
                           creationflags=CREATE_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"version": None, "disponible": False, "motivo": f"no responde a --version: {type(e).__name__}",
                "advertencia": None}
    version = version_de(r.stdout)
    if r.returncode != 0 or version is None:
        return {"version": None, "disponible": False, "motivo": "no responde a --version con una versión",
                "advertencia": None}
    texto = ".".join(map(str, version))
    if version < version_de(adaptador.version_minima):
        return {"version": texto, "disponible": False,
                "motivo": f"versión {texto} anterior a la mínima {adaptador.version_minima}", "advertencia": None}
    advertencia = None
    if version > version_de(adaptador.version_verificada):
        advertencia = f"versión no verificada: {texto} (verificada {adaptador.version_verificada})"
    return {"version": texto, "disponible": True, "motivo": None, "advertencia": advertencia}
