"""Redacción de secretos y truncado de textos antes de escribirlos en eventos o en la salida de Cowork.

La redacción por patrones no es completa (ver riesgos del design). Por eso los eventos además copian solo campos de
lista blanca y nunca contenido de archivos ni salidas de comandos.
"""
from __future__ import annotations

import re
from functools import lru_cache

REDACTADO = "[REDACTADO]"
MARCA_TRUNCADO = "…[truncado]"

# (patrón, reemplazo). El orden importa: lo más específico primero.
_PATRONES = [
    (re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)", re.DOTALL),
     REDACTADO),
    (re.compile(r"(?i)\b(authorization)(\s*[:=]\s*)[^\r\n'\"]+"), r"\1\2" + REDACTADO),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"), "Bearer " + REDACTADO),
    (re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}"), REDACTADO),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"), REDACTADO),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), REDACTADO),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), REDACTADO),
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), REDACTADO),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), REDACTADO),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), REDACTADO),
    (re.compile(r"(?i)\b(password|passwd|pwd|secret|client[_-]?secret|token|api[_-]?key|access[_-]?key)"
                r"(\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|[^\s\"',;&]+)"), r"\1\2" + REDACTADO),
]


@lru_cache(maxsize=64)
def _compilar(patrones: tuple[str, ...]) -> tuple[re.Pattern, ...]:
    return tuple(re.compile(p) for p in patrones)


def redactar(texto: str, extra=()) -> str:
    """Reemplaza por [REDACTADO] lo que parezca un secreto, más los patrones extra del proyecto."""
    if not texto:
        return texto
    for patron, reemplazo in _PATRONES:
        texto = patron.sub(reemplazo, texto)
    for patron in _compilar(tuple(extra)):
        texto = patron.sub(REDACTADO, texto)
    return texto


def truncar(texto: str, maximo: int) -> str:
    if len(texto) <= maximo:
        return texto
    return texto[: max(0, maximo - len(MARCA_TRUNCADO))] + MARCA_TRUNCADO


def validar_patrones(patrones) -> list[str]:
    """Errores de compilación de los patrones extra de un proyecto (lista vacía si están bien)."""
    errores = []
    for p in patrones:
        try:
            re.compile(p)
        except re.error as e:
            errores.append(f"patrón inválido {p!r}: {e}")
    return errores
