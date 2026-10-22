"""Git del orquestador (nunca de los agentes): auditoría, diff stat y huella del estado.

Siempre con la ruta absoluta de `herramientas.git`, `GIT_OPTIONAL_LOCKS=0` (no toma candados ni reescribe el
índice) y sin ventana. Estos comandos son del orquestador; jamás vienen de una tarea.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

from .comun import ahora
from .procesos import CREATE_NO_WINDOW


def correr_git(git: str, cwd: Path, *args: str, binario: bool = False) -> subprocess.CompletedProcess:
    entorno = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
    return subprocess.run([git, "-c", "core.quotepath=false", *args], cwd=str(cwd), capture_output=True,
                          text=not binario, encoding=None if binario else "utf-8",
                          errors=None if binario else "replace", env=entorno, stdin=subprocess.DEVNULL,
                          creationflags=CREATE_NO_WINDOW, timeout=120)


def _salida(git, cwd, *args) -> str | None:
    r = correr_git(git, cwd, *args)
    return r.stdout.strip() if r.returncode == 0 else None


def _huella_archivo(ruta: Path) -> str | None:
    try:
        return hashlib.sha256(ruta.read_bytes()).hexdigest()
    except (FileNotFoundError, IsADirectoryError, PermissionError):
        return None


def _ruta_git(git, worktree, relativa) -> Path | None:
    texto = _salida(git, worktree, "rev-parse", "--git-path", relativa)
    if not texto:
        return None
    ruta = Path(texto)
    return ruta if ruta.is_absolute() else Path(worktree) / ruta


def foto(git: str, worktree: Path, rama: str) -> dict:
    """Estado de git que un agente no debe cambiar (spec seguridad-agentes, auditoría).

    Con 3 llamadas a git (cada una cuesta cientos de ms en Windows): rutas internas en un solo `rev-parse`, refs y
    lista de worktrees. HEAD, reflogs, config y hooks se leen directo de esas rutas.
    """
    partes = ["hooks", "HEAD", "logs/HEAD", f"logs/refs/heads/{rama}", "logs/refs/stash", "config.worktree"]
    salida = _salida(git, worktree, "rev-parse", "--git-common-dir", *[x for p in partes for x in ("--git-path", p)])
    lineas = (salida or "").splitlines()
    if len(lineas) != len(partes) + 1:
        lineas = [".git", *(["-"] * len(partes))]
    comun, ganchos, archivo_head, log_head, log_rama, log_stash, config_wt = [
        Path(x) if Path(x).is_absolute() else Path(worktree) / x for x in lineas]
    lista_ganchos = []
    if ganchos.is_dir():
        lista_ganchos = sorted((p.name, _huella_archivo(p)) for p in ganchos.iterdir() if p.is_file())
    refs = sorted((_salida(git, worktree, "for-each-ref", "--format=%(refname) %(objectname)") or "").splitlines())
    try:
        texto_head = archivo_head.read_text(encoding="utf-8").strip()
    except OSError:
        texto_head = ""
    head_ref = texto_head[5:].strip() if texto_head.startswith("ref:") else None
    if head_ref:
        head = next((linea.split(" ", 1)[1] for linea in refs if linea.split(" ", 1)[0] == head_ref), None)
    else:
        head = texto_head or None
    return {
        "head_ref": head_ref, "head": head, "refs": refs,
        "reflog_head": _huella_archivo(log_head), "reflog_rama": _huella_archivo(log_rama),
        "stash": _huella_archivo(log_stash),
        "worktrees": _salida(git, worktree, "worktree", "list", "--porcelain"),
        "config": _huella_archivo(comun / "config"), "config_worktree": _huella_archivo(config_wt),
        "hooks": lista_ganchos,
    }


NOMBRES = {"head_ref": "rama actual (HEAD)", "head": "HEAD", "reflog_head": "reflog de HEAD",
           "reflog_rama": "reflog de la rama", "stash": "stash", "worktrees": "lista de worktrees",
           "config": ".git/config", "config_worktree": "config del worktree", "hooks": ".git/hooks"}


def _bloques_worktrees(texto: str | None) -> dict[str, str]:
    """`worktree list --porcelain` → {ruta normalizada: bloque}."""
    from .comun import normalizar

    bloques = {}
    for bloque in (texto or "").replace("\r\n", "\n").split("\n\n"):
        bloque = bloque.strip()
        if bloque:
            primera = bloque.splitlines()[0]
            bloques[normalizar(primera[len("worktree "):] if primera.startswith("worktree ") else primera)] = bloque
    return bloques


def diferencias(antes: dict, despues: dict, propios=frozenset()) -> list[str]:
    """Qué cambió en git entre las dos fotos.

    `propios` son los (worktree, rama) que el orquestador estuvo creando *durante* esta corrida para otra tarea del
    mismo repo (`worktrees.creados_entre`). Su alta o su cambio mientras se crea (git lo marca `locked
    initializing`) no son del agente y se ignoran; si desaparecen, sí cuenta.
    """
    rutas_propias = {ruta for ruta, _ in propios}
    ramas_propias = {f"refs/heads/{rama}" for _, rama in propios}
    cambios = []
    for clave, nombre in NOMBRES.items():
        if clave == "worktrees":
            viejos, nuevos = _bloques_worktrees(antes.get(clave)), _bloques_worktrees(despues.get(clave))
            for ruta in rutas_propias & set(nuevos):
                viejos.pop(ruta, None)
                nuevos.pop(ruta)
            if viejos != nuevos:
                cambios.append(nombre)
        elif antes.get(clave) != despues.get(clave):
            cambios.append(nombre)
    if antes.get("refs") != despues.get("refs"):
        viejas, nuevas = set(antes.get("refs") or []), set(despues.get("refs") or [])
        nombres_nuevos = {linea.split(" ", 1)[0] for linea in nuevas}
        nombres = sorted({linea.split(" ", 1)[0] for linea in viejas ^ nuevas}
                         - (ramas_propias & nombres_nuevos))
        cambios.extend(nombres)
    return cambios


def _no_seguidos(git, worktree) -> list[str]:
    r = correr_git(git, worktree, "ls-files", "--others", "--exclude-standard", "-z")
    return sorted(p for p in r.stdout.split("\0") if p) if r.returncode == 0 else []


def diffstat(git: str, worktree: Path, base: str) -> dict:
    """Archivos cambiados contra la rama base, incluidos los nuevos sin seguimiento (solo nombres y líneas)."""
    archivos = []
    r = correr_git(git, worktree, "diff", "--numstat", base)
    if r.returncode == 0:
        for linea in r.stdout.splitlines():
            partes = linea.split("\t")
            if len(partes) >= 3:
                binario = partes[0] == "-"
                archivos.append({"ruta": partes[-1], "agregadas": None if binario else int(partes[0]),
                                 "borradas": None if binario else int(partes[1]), "nuevo": False,
                                 "binario": binario})
    for relativa in _no_seguidos(git, worktree):
        try:
            contenido = (Path(worktree) / relativa).read_bytes()
        except OSError:
            continue
        binario = b"\0" in contenido[:8000]
        lineas = None if binario else contenido.count(b"\n") + (1 if contenido and not contenido.endswith(b"\n") else 0)
        archivos.append({"ruta": relativa, "agregadas": lineas, "borradas": 0 if not binario else None,
                         "nuevo": True, "binario": binario})
    return {"calculado": ahora(), "base": base, "archivos": archivos,
            "total": {"archivos": len(archivos), "agregadas": sum(a["agregadas"] or 0 for a in archivos),
                      "borradas": sum(a["borradas"] or 0 for a in archivos)}}


def huella_estado(git: str, worktree: Path, tarea: str, intento: int, informe: Path) -> str:
    """SHA-256 de lo que Sebastian aprueba (spec aprobacion-gates): HEAD, diff, archivos nuevos e informe."""
    h = hashlib.sha256()
    h.update(f"{tarea}\n{intento}\n".encode())
    h.update((_salida(git, worktree, "rev-parse", "-q", "--verify", "HEAD") or "sin-head").encode())
    diff = correr_git(git, worktree, "diff", "--binary", "HEAD", binario=True)
    h.update(hashlib.sha256(diff.stdout if diff.returncode == 0 else b"").digest())
    for relativa in _no_seguidos(git, worktree):
        h.update(relativa.encode() + b"\0" + (_huella_archivo(Path(worktree) / relativa) or "").encode())
    h.update((_huella_archivo(informe) or "sin-informe").encode())
    return h.hexdigest()
