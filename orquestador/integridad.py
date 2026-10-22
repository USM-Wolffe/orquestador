"""Aviso de integridad del código del orquestador (spec aprobacion-gates, decisión 23).

Al iniciar `orq correr` se revisa si el código de la instalación (`orquestador/` y `orq.py`) tiene cambios sin
commit, incluidos archivos nuevos. Si los tiene, o si no se puede verificar, los gates quedan deshabilitados salvo
que se arranque con `--permitir-codigo-modificado`.
"""
from __future__ import annotations

from pathlib import Path

from .git import correr_git

INSTALACION = Path(__file__).resolve().parent.parent
RUTAS_CODIGO = ("orquestador", "orq.py")


def revisar(git: str | None, carpeta: Path = INSTALACION) -> list[str]:
    """Archivos de código con cambios sin commit. Si no se puede verificar, devuelve el motivo como único elemento."""
    if not git:
        return ["no se pudo verificar: falta herramientas.git en la config"]
    try:
        r = correr_git(git, carpeta, "status", "--porcelain=v1", "--untracked-files=all", "--", *RUTAS_CODIGO)
    except OSError as e:
        return [f"no se pudo verificar: {e}"]
    if r.returncode != 0:
        return ["no se pudo verificar: la instalación no es un repo git"]
    cambios = []
    for linea in r.stdout.splitlines():
        ruta = linea[3:].strip().strip('"')
        if "__pycache__" in ruta or ruta.endswith(".pyc"):
            continue
        cambios.append(ruta)
    return cambios
