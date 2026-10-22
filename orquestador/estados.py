"""Máquina de estados de las tareas (spec registro-tareas).

Cada transición se valida contra una tabla de (estado de origen, estado de destino) → actores y vías permitidos,
y queda en el historial. Los gates solo se deciden por el tablero (`via="tablero"`), nunca por archivos.
"""
from __future__ import annotations

ESTADOS = ("pendiente", "bloqueada", "en_curso", "esperando_gate", "hecha", "fallida", "cancelada")
TERMINALES = frozenset({"hecha", "cancelada"})
NO_TERMINALES = tuple(e for e in ESTADOS if e not in TERMINALES)
ACTORES = ("orquestador", "cowork", "sebastian")

# Quién puede pedir cada transición y por qué vía:
#   orquestador → vía None (el propio bucle)
#   cowork      → vía "entrada" (carpeta de Cowork)
#   sebastian   → vía "cli" (orq tarea) o "tablero" (solo gates)
_ORQ = frozenset({("orquestador", None)})
_PEDIDO = frozenset({("cowork", "entrada"), ("sebastian", "cli")})
_GATE = frozenset({("sebastian", "tablero")})

PERMITIDAS: dict[tuple[str, str], frozenset] = {
    ("bloqueada", "pendiente"): _ORQ,
    ("pendiente", "bloqueada"): _ORQ,
    ("pendiente", "en_curso"): _ORQ,
    ("en_curso", "esperando_gate"): _ORQ,
    ("en_curso", "hecha"): _ORQ,
    ("en_curso", "pendiente"): _ORQ,
    ("en_curso", "fallida"): _ORQ,
    ("esperando_gate", "hecha"): _GATE,
    ("esperando_gate", "pendiente"): _GATE,
    ("fallida", "pendiente"): _PEDIDO,
    **{(de, "cancelada"): _PEDIDO for de in NO_TERMINALES},
}


class TransicionInvalida(ValueError):
    pass


def puede(de: str | None, a: str, por: str, via: str | None = None) -> bool:
    return (por, via) in PERMITIDAS.get((de, a), frozenset())


def _anotar(tarea: dict, de, a: str, por: str, motivo: str, momento: str, via: str | None, **extra) -> dict:
    entrada = {"de": de, "a": a, "por": por, "en": momento, "motivo": motivo}
    if via is not None:
        entrada["via"] = via
    entrada.update({k: v for k, v in extra.items() if v is not None})
    tarea.setdefault("historial", []).append(entrada)
    tarea["estado"] = a
    tarea["actualizada"] = momento
    if a in TERMINALES:
        tarea["terminada"] = momento
    return entrada


def transicion(tarea: dict, a: str, por: str, motivo: str, momento: str, via: str | None = None, **extra) -> dict:
    de = tarea.get("estado")
    if a not in ESTADOS or not puede(de, a, por, via):
        raise TransicionInvalida(f"transición no permitida: {de} → {a} por {por} (vía {via})")
    return _anotar(tarea, de, a, por, motivo, momento, via, **extra)


def anotar(tarea: dict, por: str, motivo: str, momento: str) -> dict:
    """Deja una nota en el historial sin cambiar de estado (p. ej. 'la sesión no existía; se abrió una nueva')."""
    estado = tarea.get("estado")
    entrada = {"de": estado, "a": estado, "por": por, "en": momento, "motivo": motivo}
    tarea.setdefault("historial", []).append(entrada)
    tarea["actualizada"] = momento
    return entrada


def crear(tarea: dict, por: str, momento: str, deps_abiertas: list[str], via: str | None = None) -> dict:
    """Estado inicial: `bloqueada` si tiene dependencias abiertas; si no, `pendiente`."""
    if tarea.get("estado") is not None:
        raise TransicionInvalida("la tarea ya tiene estado")
    if deps_abiertas:
        tarea["motivo"] = "dependencias abiertas: " + ", ".join(deps_abiertas)
        return _anotar(tarea, None, "bloqueada", por, "creada", momento, via)
    tarea["motivo"] = None
    return _anotar(tarea, None, "pendiente", por, "creada", momento, via)


def reintentar(tarea: dict, por: str, via: str, momento: str) -> dict:
    if tarea.get("estado") != "fallida":
        raise TransicionInvalida(f"solo se reintenta una tarea fallida (está {tarea.get('estado')})")
    entrada = transicion(tarea, "pendiente", por, "reintento", momento, via=via)
    tarea["max_intentos"] = int(tarea.get("intentos", 0)) + 1
    tarea["motivo"] = None
    return entrada


def pedir_cancelacion(tarea: dict, por: str, via: str, momento: str) -> str:
    """Cancela de inmediato, o deja pedida la cancelación si la tarea está en curso (el bucle mata el proceso)."""
    estado = tarea.get("estado")
    if estado in TERMINALES or estado not in ESTADOS or not puede(estado, "cancelada", por, via):
        raise TransicionInvalida(f"no se puede cancelar una tarea {estado} (por {por}, vía {via})")
    if estado == "en_curso":
        tarea["cancelacion"] = {"por": por, "via": via, "pedida": momento}
        tarea["actualizada"] = momento
        return "pedida"
    transicion(tarea, "cancelada", por, "cancelada", momento, via=via)
    return "cancelada"


def ejecutar_cancelacion(tarea: dict, momento: str) -> dict:
    """La llama el bucle después de terminar el proceso del agente."""
    pedida = tarea.get("cancelacion")
    if not pedida:
        raise TransicionInvalida("no hay una cancelación pedida")
    return transicion(tarea, "cancelada", pedida["por"], "cancelada", momento, via=pedida["via"])


def decidir_gate(tarea: dict, decision: str, por: str, via: str | None, momento: str, nota: str | None = None,
                 huella: str | None = None, sesion: str | None = None, **marcas) -> dict:
    """Aprueba o rechaza un gate. Solo Sebastian y solo desde el tablero (spec aprobacion-gates)."""
    if decision not in ("aprobar", "rechazar"):
        raise TransicionInvalida(f"decisión de gate desconocida: {decision}")
    if decision == "rechazar" and not (nota or "").strip():
        raise TransicionInvalida("rechazar un gate exige una nota")
    destino = "hecha" if decision == "aprobar" else "pendiente"
    if tarea.get("estado") != "esperando_gate" or not puede("esperando_gate", destino, por, via):
        raise TransicionInvalida(f"decisión de gate no permitida (estado {tarea.get('estado')}, por {por}, vía {via})")
    entrada = transicion(tarea, destino, por, "gate aprobado" if decision == "aprobar" else "gate rechazado",
                         momento, via=via, huella=huella, sesion=sesion, **marcas)
    gate = tarea.setdefault("gate", {})
    gate.update(decision="aprobada" if decision == "aprobar" else "rechazada", nota=nota, en=momento,
                huella=huella, via=via)
    return entrada
