"""Sesiones por (cambio, agente) de un proyecto: `sesiones.json` (spec planificacion-ejecucion).

La sesión se guarda apenas se conoce (en cc, antes de lanzar). Un candado la protege porque la usan el bucle y los
hilos de las corridas del mismo proceso.
"""
from __future__ import annotations

import threading
from pathlib import Path

from .comun import escribir_json, leer_json


class Sesiones:
    def __init__(self, ruta: Path):
        self.ruta = Path(ruta)
        self._lock = threading.Lock()
        datos = leer_json(self.ruta, {}) or {}
        self._datos: dict[str, str] = datos if isinstance(datos, dict) else {}

    @staticmethod
    def clave(cambio: str, agente: str) -> str:
        return f"{cambio}|{agente}"

    def obtener(self, cambio: str, agente: str) -> str | None:
        with self._lock:
            return self._datos.get(self.clave(cambio, agente))

    def guardar(self, cambio: str, agente: str, sesion: str) -> None:
        with self._lock:
            self._datos[self.clave(cambio, agente)] = sesion
            self.ruta.parent.mkdir(parents=True, exist_ok=True)
            escribir_json(self.ruta, self._datos)

    def borrar(self, cambio: str, agente: str) -> None:
        with self._lock:
            if self._datos.pop(self.clave(cambio, agente), None) is not None:
                escribir_json(self.ruta, self._datos)
