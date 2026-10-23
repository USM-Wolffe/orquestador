"""Candado de instancia: un solo `orq correr` por raíz de estado (spec proyectos).

El candado guarda el pid y la hora de creación del proceso: si Windows reutilizó el pid para otro proceso, el
candado se trata como abandonado.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .comun import ahora
from .procesos import hora_creacion, proceso_vivo

__all__ = ["Candado", "CandadoOcupado", "proceso_vivo"]


class CandadoOcupado(Exception):
    """Otra instancia viva tiene la raíz de estado."""


class Candado:
    def __init__(self, ruta: Path):
        self.ruta = ruta
        self.tomado = False
        self.puerto: int | None = None

    def fijar_puerto(self, puerto: int) -> None:
        """Guarda el puerto del tablero en el candado (lo lee `orq abrir`); solo lo escribe el dueño."""
        self.puerto = int(puerto)
        if not self.tomado:
            return
        try:
            datos = json.loads(self.ruta.read_text(encoding="utf-8"))
            if datos.get("pid") != os.getpid():
                return
        except (OSError, ValueError, AttributeError):
            datos = {"pid": os.getpid(), "creado": hora_creacion(os.getpid()), "desde": ahora()}
        datos["puerto"] = self.puerto
        with open(self.ruta, "w", encoding="utf-8") as f:
            json.dump(datos, f)

    def _crear(self) -> None:
        fd = os.open(self.ruta, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid(), "creado": hora_creacion(os.getpid()), "desde": ahora()}, f)
        self.tomado = True

    def tomar(self) -> str | None:
        """Toma el candado. Devuelve un aviso si había uno abandonado; lanza CandadoOcupado si hay otra instancia."""
        try:
            self._crear()
            return None
        except FileExistsError:
            pass
        try:
            datos = json.loads(self.ruta.read_text(encoding="utf-8"))
            pid, creado = datos.get("pid"), datos.get("creado")
        except (OSError, ValueError, AttributeError):
            pid, creado = None, None
        if pid == os.getpid() and creado in (None, hora_creacion(os.getpid())):
            raise CandadoOcupado("ya hay un orquestador corriendo con esta raíz de estado (este mismo proceso)")
        if pid is not None and pid != os.getpid() and proceso_vivo(pid, creado):
            raise CandadoOcupado(f"ya hay un orquestador corriendo con esta raíz de estado (pid {pid})")
        self.ruta.unlink(missing_ok=True)
        self._crear()
        return f"candado abandonado del pid {pid} reemplazado"

    def soltar(self) -> None:
        if not self.tomado:
            return
        try:
            if json.loads(self.ruta.read_text(encoding="utf-8")).get("pid") == os.getpid():
                self.ruta.unlink(missing_ok=True)
        except (OSError, ValueError, AttributeError):
            pass
        self.tomado = False
