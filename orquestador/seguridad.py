"""Controles de seguridad comunes a todos los agentes (spec seguridad-agentes).

- Revisión del comando contra las banderas prohibidas del agente, aunque lo haya armado el adaptador.
- Entorno filtrado: sin variables con forma de secreto.
- Worktree sin secretos y sin skills del repo que concedan permisos sin huella aprobada.
- El prompt solo por stdin; en el comando, solo valores validados.
- Matriz de garantías declarada por agente y plataforma.
"""
from __future__ import annotations

import fnmatch
import hashlib
import os
import re
import sys
from pathlib import Path

PATRONES_SECRETO = ("*KEY*", "*TOKEN*", "*SECRET*", "*PASSWORD*", "*PASSWD*", "*CREDENTIAL*", "AWS_*", "EMBUDO_*",
                    "GH_*", "GITHUB_*")
ARCHIVOS_SECRETO = (".env", ".env.*", "id_rsa*", "*.pem", "*.pfx", "*.p12")
ARCHIVOS_PERMITIDOS = (".env.example",)
CARPETAS_OMITIDAS = frozenset({".git"})
UUID_OK = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
CAMPOS_SKILL_PELIGROSOS = re.compile(r"^(allowed-tools|hooks)\s*:", re.MULTILINE)

# Niveles: "duro" (no hay camino con los permisos dados), "sandbox" (lo impone el sandbox del sistema operativo)
# o "instruccion" (depende del modelo, o de una regla que se rodea con un intérprete). Ver design D7.
MATRIZ = {
    ("cc", "windows"): {"bypass": "duro", "git": "instruccion", "credenciales": "instruccion",
                        "escritura": "instruccion", "red": "instruccion"},
    # En E1 el sandbox de Claude Code no se activa en ninguna plataforma: mismos niveles fuera de Windows.
    ("cc", "otra"): {"bypass": "duro", "git": "instruccion", "credenciales": "instruccion",
                     "escritura": "instruccion", "red": "instruccion"},
}


class ErrorSeguridad(Exception):
    """El lanzamiento no cumple un control obligatorio: la tarea queda con error de clase `seguridad`."""


def plataforma() -> str:
    return "windows" if sys.platform == "win32" else "otra"


def niveles(agente: str, plataforma_actual: str | None = None) -> dict:
    return dict(MATRIZ[(agente, plataforma_actual or plataforma())])


def es_secreto(nombre: str) -> bool:
    mayus = nombre.upper()
    return any(fnmatch.fnmatchcase(mayus, p) for p in PATRONES_SECRETO)


def entorno_filtrado(base, permitidas=()) -> dict[str, str]:
    permitidas = {p.upper() for p in permitidas}
    return {k: v for k, v in base.items() if k.upper() in permitidas or not es_secreto(k)}


def revisar_comando(adaptador, argv: list[str]) -> None:
    for token in argv:
        bandera, _, valor_igual = token.partition("=")
        if token in adaptador.banderas_prohibidas or bandera in adaptador.banderas_prohibidas:
            raise ErrorSeguridad(f"bandera prohibida en el comando de {adaptador.nombre}: {bandera}")
        if "bypasspermissions" in token.lower():
            raise ErrorSeguridad(f"valor prohibido en el comando de {adaptador.nombre}: {token}")
        if valor_igual and valor_igual in adaptador.valores_prohibidos.get(bandera, ()):
            raise ErrorSeguridad(f"valor prohibido en el comando de {adaptador.nombre}: {token}")
    for i, token in enumerate(argv[:-1]):
        if argv[i + 1] in adaptador.valores_prohibidos.get(token, ()):
            raise ErrorSeguridad(f"valor prohibido en el comando de {adaptador.nombre}: {token} {argv[i + 1]}")


def revisar_lanzamiento(adaptador, lanz, prompt: str) -> None:
    """Banderas prohibidas, y que el texto libre de la tarea no viaje en los argumentos."""
    revisar_comando(adaptador, lanz.argv)
    if prompt and prompt.strip():
        for token in lanz.argv:
            if prompt.strip() in token:
                raise ErrorSeguridad("el prompt de la tarea no puede ir en los argumentos del agente")
    if lanz.stdin != prompt:
        raise ErrorSeguridad("el prompt debe ir solo por la entrada estándar")


def _es_archivo_secreto(nombre: str) -> bool:
    if nombre in ARCHIVOS_PERMITIDOS:
        return False
    return any(fnmatch.fnmatch(nombre.lower(), p) for p in ARCHIVOS_SECRETO)


def _sha256(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def revisar_worktree(worktree: Path, huellas_aprobadas: dict[str, str]) -> None:
    """Secretos y skills peligrosas en el worktree. Nombra rutas, nunca muestra contenido."""
    secretos, skills = [], []
    for raiz, carpetas, archivos in os.walk(worktree):
        carpetas[:] = [c for c in carpetas if c not in CARPETAS_OMITIDAS]
        actual = Path(raiz)
        for nombre in archivos:
            ruta = actual / nombre
            relativa = ruta.relative_to(worktree).as_posix()
            if _es_archivo_secreto(nombre):
                secretos.append(relativa)
            elif nombre == "SKILL.md" and actual.parent.name == "skills" and actual.parent.parent.name == ".claude":
                try:
                    texto = ruta.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                cabecera = texto.split("---", 2)[1] if texto.startswith("---") and texto.count("---") >= 2 else ""
                if CAMPOS_SKILL_PELIGROSOS.search(cabecera) and huellas_aprobadas.get(relativa) != _sha256(ruta):
                    skills.append(relativa)
    if secretos:
        raise ErrorSeguridad("archivos con secretos en el worktree: " + ", ".join(sorted(secretos)))
    if skills:
        raise ErrorSeguridad("skills del repo con allowed-tools o hooks sin huella aprobada: "
                             + ", ".join(sorted(skills)))


def sesion_valida(sesion) -> bool:
    return isinstance(sesion, str) and bool(UUID_OK.match(sesion))
