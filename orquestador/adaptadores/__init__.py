"""Adaptadores de agente (spec adaptadores-agente). E1: solo `cc`."""
from __future__ import annotations

from .base import Adaptador
from .cc import AdaptadorCC


def adaptadores_de(config) -> dict[str, Adaptador]:
    """Un adaptador por agente configurado que el orquestador conoce."""
    disponibles = {"cc": AdaptadorCC}
    return {nombre: disponibles[nombre](agente) for nombre, agente in config.agentes.items() if nombre in disponibles}
