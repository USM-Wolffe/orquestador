"""Arranque común de `orq correr`: config, proyectos, ubicaciones, carpetas y candado.

Todo lo que puede fallar se revisa antes de escribir: si la configuración no sirve, no se crea nada.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .candado import Candado
from .comun import registrar
from .config import Config, ErrorConfig, cargar_config, validar_ubicaciones
from .proyectos import Proyecto, cargar_proyectos


@dataclass
class Contexto:
    config: Config
    proyectos: list[Proyecto]
    candado: Candado

    @property
    def activos(self) -> list[Proyecto]:
        return [p for p in self.proyectos if p.activo]

    def cerrar(self) -> None:
        self.candado.soltar()


def iniciar(config: Path | str | None = None, raiz: Path | str | None = None) -> Contexto:
    c = cargar_config(config, raiz)
    proyectos = cargar_proyectos(c)
    validar_ubicaciones(c, proyectos)
    if c.git is None:
        raise ErrorConfig(f"herramientas.git: {c.git_motivo}")
    c.raiz.mkdir(parents=True, exist_ok=True)
    candado = Candado(c.raiz / "orquestador.lock")
    aviso = candado.tomar()  # lanza CandadoOcupado antes de escribir nada más
    try:
        c.carpeta_proyectos.mkdir(exist_ok=True)
        if aviso:
            registrar(c.raiz, aviso)
        for p in proyectos:
            for error in p.errores:
                registrar(c.raiz, f"proyecto '{p.nombre}' inactivo: {error}")
            for advertencia in p.advertencias:
                registrar(c.raiz, f"proyecto '{p.nombre}': {advertencia}")
            if p.activo:
                for sub in ("entrada", "respuestas", "salida"):
                    (p.carpeta_cowork / sub).mkdir(parents=True, exist_ok=True)
                p.carpeta_decisiones.mkdir(exist_ok=True)
                p.carpeta_eventos.mkdir(exist_ok=True)
        for nombre, agente in c.agentes.items():
            if not agente.disponible:
                registrar(c.raiz, f"agente '{nombre}' no disponible: {agente.motivo or 'deshabilitado'}")
    except BaseException:
        candado.soltar()
        raise
    return Contexto(config=c, proyectos=proyectos, candado=candado)
