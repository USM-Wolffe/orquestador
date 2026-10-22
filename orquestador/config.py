"""Configuración global del orquestador (spec proyectos, estado-cowork y adaptadores-agente).

Dónde vive:
- La raíz de estado sale de `--raiz`, de `ORQ_RAIZ`, de `raiz_estado` en `config.json` o, por defecto, de
  `%USERPROFILE%\\.orquestador`.
- `config.json` se busca en `--config`, en `ORQ_CONFIG` o en la raíz inicial (argumento, variable o defecto).

Los ejecutables (agentes y git) son rutas absolutas: nunca se buscan en el PATH.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .comun import esta_dentro

AGENTES_CONOCIDOS = ("cc",)  # E1; codex en E2 y cursor en E4
PUERTO_POR_DEFECTO = 8765


class ErrorConfig(Exception):
    """Configuración inválida: el orquestador no debe correr ni escribir nada."""


@dataclass
class Agente:
    nombre: str
    ejecutable: list[str] | None
    habilitado: bool
    restricted: bool
    motivo: str | None = None

    @property
    def disponible(self) -> bool:
        return self.habilitado and self.ejecutable is not None and self.motivo is None


@dataclass
class Config:
    archivo: Path
    raiz: Path
    cowork_raiz: Path
    limite_global: int
    limite_por_agente: dict[str, int]
    agentes: dict[str, Agente]
    git: str | None
    git_motivo: str | None
    puerto: int
    eventos_tope_bytes: int
    eventos_rotados: int
    intervalo_s: float = 2.0
    datos: dict = field(default_factory=dict)

    @property
    def carpeta_proyectos(self) -> Path:
        return self.raiz / "proyectos"


def _perfil() -> Path:
    return Path(os.environ.get("USERPROFILE") or Path.home())


def raiz_por_defecto() -> Path:
    return _perfil() / ".orquestador"


def cowork_por_defecto() -> Path:
    return _perfil() / "Orquestador-Cowork"


def _expandir(texto: str) -> str:
    return os.path.expandvars(os.path.expanduser(texto))


def resolver_ejecutable(valor) -> tuple[list[str] | None, str | None]:
    """Valida un ejecutable de la config: ruta absoluta (o lista que empieza con una) que existe como archivo."""
    if isinstance(valor, str) and valor.strip():
        partes = [valor]
    elif isinstance(valor, list) and valor and all(isinstance(x, str) and x for x in valor):
        partes = list(valor)
    else:
        return None, "el ejecutable no está definido o tiene un formato inválido"
    primero = _expandir(partes[0])
    if not Path(primero).is_absolute():
        return None, "el ejecutable debe ser una ruta absoluta"
    if not os.path.isfile(primero):
        return None, f"el ejecutable no existe: {primero}"
    return [primero, *partes[1:]], None


def _entero(datos: dict, clave: str, defecto: int, minimo: int = 1) -> int:
    valor = datos.get(clave, defecto)
    if not isinstance(valor, int) or isinstance(valor, bool) or valor < minimo:
        raise ErrorConfig(f"'{clave}' debe ser un entero mayor o igual a {minimo}")
    return valor


def cargar_config(config: Path | str | None = None, raiz: Path | str | None = None) -> Config:
    raiz_inicial = Path(raiz) if raiz else Path(os.environ["ORQ_RAIZ"]) if os.environ.get("ORQ_RAIZ") else None
    archivo = Path(config) if config else Path(os.environ["ORQ_CONFIG"]) if os.environ.get("ORQ_CONFIG") else \
        (raiz_inicial or raiz_por_defecto()) / "config.json"
    try:
        datos = json.loads(archivo.read_text(encoding="utf-8")) if archivo.exists() else {}
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ErrorConfig(f"{archivo} no es JSON válido: {e}") from e
    if not isinstance(datos, dict):
        raise ErrorConfig(f"{archivo} debe ser un objeto JSON")

    if raiz_inicial is not None:
        raiz_final = raiz_inicial
    elif datos.get("raiz_estado"):
        raiz_final = Path(_expandir(str(datos["raiz_estado"])))
    else:
        raiz_final = raiz_por_defecto()
    cowork = Path(_expandir(str(datos["cowork_raiz"]))) if datos.get("cowork_raiz") else cowork_por_defecto()
    for nombre, ruta in (("raiz_estado", raiz_final), ("cowork_raiz", cowork)):
        if not ruta.is_absolute():
            raise ErrorConfig(f"'{nombre}' debe ser una ruta absoluta")

    limites = datos.get("limites", {}) or {}
    if not isinstance(limites, dict):
        raise ErrorConfig("'limites' debe ser un objeto")
    limite_global = _entero(limites, "global", 2)
    por_agente_crudo = limites.get("por_agente", {}) or {}
    if not isinstance(por_agente_crudo, dict):
        raise ErrorConfig("'limites.por_agente' debe ser un objeto")
    por_agente = {n: _entero(por_agente_crudo, n, 1) for n in por_agente_crudo}

    agentes: dict[str, Agente] = {}
    for nombre, definicion in (datos.get("agentes", {}) or {}).items():
        if nombre not in AGENTES_CONOCIDOS:
            continue  # agentes de etapas futuras: se ignoran en E1
        if not isinstance(definicion, dict):
            raise ErrorConfig(f"'agentes.{nombre}' debe ser un objeto")
        partes, motivo = resolver_ejecutable(definicion.get("ejecutable"))
        agentes[nombre] = Agente(nombre=nombre, ejecutable=partes, habilitado=definicion.get("habilitado", True) is True,
                                 restricted=definicion.get("restricted", True) is not False, motivo=motivo)

    herramientas = datos.get("herramientas", {}) or {}
    git, git_motivo = resolver_ejecutable(herramientas.get("git"))

    tablero = datos.get("tablero", {}) or {}
    puerto = _entero(tablero, "puerto", PUERTO_POR_DEFECTO, minimo=1024)
    if puerto > 65535:
        raise ErrorConfig("'tablero.puerto' fuera de rango")
    eventos = datos.get("eventos", {}) or {}
    tope_mb = eventos.get("tope_mb", 10)
    if not isinstance(tope_mb, (int, float)) or isinstance(tope_mb, bool) or tope_mb <= 0:
        raise ErrorConfig("'eventos.tope_mb' debe ser un número positivo")
    rotados = _entero(eventos, "rotados", 5)
    intervalo = datos.get("intervalo_s", 2.0)
    if not isinstance(intervalo, (int, float)) or isinstance(intervalo, bool) or not 0.1 <= intervalo <= 300:
        raise ErrorConfig("'intervalo_s' debe estar entre 0,1 y 300 segundos")

    return Config(archivo=archivo, raiz=raiz_final, cowork_raiz=cowork, limite_global=limite_global,
                  limite_por_agente=por_agente, agentes=agentes, git=git[0] if git else None, git_motivo=git_motivo,
                  puerto=puerto, eventos_tope_bytes=int(tope_mb * 1024 * 1024), eventos_rotados=rotados,
                  intervalo_s=float(intervalo), datos=datos)


def validar_ubicaciones(config: Config, proyectos) -> None:
    """Raíz de estado y carpeta de Cowork: separadas entre sí y fuera de todo repo y worktree registrado."""
    if esta_dentro(config.cowork_raiz, config.raiz):
        raise ErrorConfig(f"la carpeta de Cowork ({config.cowork_raiz}) no puede estar dentro de la raíz de estado")
    if esta_dentro(config.raiz, config.cowork_raiz):
        raise ErrorConfig(f"la raíz de estado ({config.raiz}) no puede estar dentro de la carpeta de Cowork")
    for p in proyectos:
        if p.repo is None:
            continue
        lugares = [p.repo, *p.worktrees_existentes()]
        for lugar in lugares:
            if esta_dentro(config.raiz, lugar):
                raise ErrorConfig(f"la raíz de estado queda dentro del repo o de un worktree del proyecto "
                                  f"'{p.nombre}' ({lugar})")
            if esta_dentro(config.cowork_raiz, lugar):
                raise ErrorConfig(f"la carpeta de Cowork queda dentro del repo o de un worktree del proyecto "
                                  f"'{p.nombre}' ({lugar})")
