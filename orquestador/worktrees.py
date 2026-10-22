"""Un worktree por cambio (spec planificacion-ejecucion): `<carpeta_worktrees>\\wt-<cambio>`.

Se crea desde la rama base si no existe y se reutiliza si existe. La creación se serializa por repo (dos
`git worktree add` a la vez pueden chocar en `.git/worktrees`). El orquestador nunca borra worktrees ni ramas.

Cada creación queda anotada con su inicio (antes de correr git) y su fin, para que la auditoría de otra corrida en
paralelo en el mismo repo no confunda ese worktree y esa rama con un cambio de su agente. Solo cuentan como
propios los que se crearon *durante* esa corrida (ver `creados_entre`).
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from .comun import NOMBRE_OK, normalizar
from .git import correr_git

_candados: dict[str, threading.Lock] = {}
_candado_global = threading.Lock()
_creados: dict[str, list[dict]] = {}


def creados_entre(repo: Path, desde: float, hasta: float) -> frozenset[tuple[str, str]]:
    """(worktree normalizado, rama) que el orquestador estuvo creando en algún momento entre `desde` y `hasta`
    (reloj monótono)."""
    with _candado_global:
        return frozenset((c["ruta"], c["rama"]) for c in _creados.get(normalizar(repo), [])
                         if c["inicio"] <= hasta and (c["fin"] is None or c["fin"] >= desde))


def _registrar(repo: Path, destino: Path, rama: str) -> dict:
    entrada = {"ruta": normalizar(destino), "rama": rama, "inicio": time.monotonic(), "fin": None}
    with _candado_global:
        _creados.setdefault(normalizar(repo), []).append(entrada)
    return entrada


class ErrorWorktree(Exception):
    pass


def _candado_de(repo: Path) -> threading.Lock:
    clave = os.path.normcase(os.path.realpath(repo))
    with _candado_global:
        return _candados.setdefault(clave, threading.Lock())


def ruta_worktree(proyecto, cambio: str) -> Path:
    return Path(proyecto.carpeta_worktrees) / f"wt-{cambio}"


def asegurar(git: str, proyecto, cambio: str, rama: str, base: str | None = None, ejecutar=correr_git) -> Path:
    if not NOMBRE_OK.match(cambio) or not NOMBRE_OK.match(rama):
        raise ErrorWorktree("cambio o rama inválidos")
    destino = ruta_worktree(proyecto, cambio)
    with _candado_de(proyecto.repo):
        if (destino / ".git").exists():
            return destino
        if destino.exists():
            raise ErrorWorktree(f"{destino} existe y no es un worktree")
        existe = ejecutar(git, proyecto.repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{rama}").returncode == 0
        anotado = _registrar(proyecto.repo, destino, rama)
        try:
            if existe:
                r = ejecutar(git, proyecto.repo, "worktree", "add", str(destino), rama)
            else:
                r = ejecutar(git, proyecto.repo, "worktree", "add", "-b", rama, str(destino), base or proyecto.base)
        finally:
            anotado["fin"] = time.monotonic()
        if r.returncode != 0:
            raise ErrorWorktree(f"git worktree add falló: {(r.stderr or '').strip()[-500:]}")
    return destino
