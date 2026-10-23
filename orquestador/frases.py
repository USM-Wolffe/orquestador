"""Frases en lenguaje simple (design D6): eventos a frases, estados de estación y frases de error.

Funciones puras, sin E/S. Las rutas ya vienen relativas al worktree y con `/` desde `eventos.py`.
Los mensajes del agente no generan frase y las negaciones se muestran siempre.
"""
from __future__ import annotations

import datetime as dt
import re

_VERBOS_HERRAMIENTA = {
    "leer": "leer", "buscar": "buscar", "web": "consultar la web", "skill": "usar una skill",
    "tareas": "ordenar sus pendientes", "editar": "editar", "escribir": "escribir",
}


def _hhmm(valor) -> str | None:
    if valor is None:
        return None
    if isinstance(valor, dt.datetime):
        return valor.strftime("%H:%M")
    texto = str(valor)
    try:
        return dt.datetime.fromisoformat(texto).strftime("%H:%M")
    except ValueError:
        m = re.search(r"(\d{1,2}):(\d{2})", texto)
        return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


def frase_error(clase: str | None, reinicio=None) -> str:
    """Frase de una clase de error, con mayúscula inicial (design D6)."""
    if clase == "limite_uso" or clase == "limite":
        hora = _hhmm(reinicio)
        return f"Se le acabó el plan; sigue a las {hora}" if hora else "Se le acabó el plan"
    if clase == "seguridad":
        return "Se detuvo por seguridad"
    if clase == "violacion":
        return "Se detuvo: tocó git"
    if clase == "timeout":
        return "Se le acabó el tiempo"
    if clase == "cancelada":
        return "Se canceló"
    return "Falló el agente"


def _comando_corto(comando: str) -> str:
    palabras = (comando or "").strip().split()
    if len(palabras) >= 2 and palabras[0] == "git":
        return " ".join(palabras[:2])
    return " ".join(palabras[:3]) if palabras else "un comando"


def _es_pruebas(comando: str) -> bool:
    return "unittest" in comando or "pytest" in comando


def _es_git_lectura(comando: str) -> bool:
    palabras = comando.strip().split()
    return len(palabras) >= 2 and palabras[0] == "git" and palabras[1] in (
        "status", "diff", "log", "show", "branch", "rev-parse", "ls-files", "grep")


def frase_evento(tipo: str, datos: dict | None = None) -> str | None:
    """Frase de un evento, o None si no lleva frase (los `mensaje` nunca la llevan)."""
    datos = datos or {}
    # Las negaciones se muestran siempre, sea el tipo que sea.
    if datos.get("estado") == "negado":
        if tipo == "comando":
            return f"Intentó {_comando_corto(str(datos.get('comando') or ''))} y se le negó"
        nombre = str(datos.get("nombre") or "")
        verbo = _VERBOS_HERRAMIENTA.get(nombre, nombre or "eso")
        objetivo = datos.get("objetivo")
        detalle = f" {objetivo}" if verbo in ("leer", "editar", "escribir") and objetivo else ""
        return f"Intentó {verbo}{detalle} y se le negó"
    if tipo == "inicio":
        return "Retomó su sesión" if datos.get("retomada") else "Empezó"
    if tipo == "herramienta":
        nombre = str(datos.get("nombre") or "")
        objetivo = datos.get("objetivo")
        if nombre == "leer":
            return f"Leyó {objetivo}" if objetivo else "Leyó un archivo"
        if nombre == "buscar":
            return "Buscó en el código"
        if nombre == "web":
            return "Consultó la web"
        if nombre == "skill":
            return f"Usó la skill {objetivo}" if objetivo else "Usó una skill"
        if nombre == "tareas":
            return "Ordenó sus pendientes"
        if nombre == "editar":
            return f"Editó {objetivo}" if objetivo else "Editó un archivo"
        if nombre == "escribir":
            return f"Escribió {objetivo}" if objetivo else "Escribió un archivo"
        if nombre.startswith("otra:"):
            return f"Usó la herramienta {nombre[5:]}"
        if nombre.startswith("mcp:"):
            return f"Usó la herramienta {nombre}"
        return f"Usó la herramienta {nombre}" if nombre else "Usó una herramienta"
    if tipo == "archivo":
        ruta = datos.get("ruta") or "un archivo"
        return f"Escribió {ruta}" if datos.get("accion") == "escribir" else f"Editó {ruta}"
    if tipo == "comando":
        comando = str(datos.get("comando") or "")
        if _es_pruebas(comando):
            return "Corrió las pruebas: fallaron" if datos.get("estado") == "error" else "Corrió las pruebas"
        if _es_git_lectura(comando):
            return "Revisó git"
        if "openspec" in comando and "validate" in comando:
            return "Validó con OpenSpec"
        return "Corrió un comando"
    if tipo == "fin":
        return "Terminó y entregó su informe" if datos.get("ok") else "Terminó con error"
    if tipo == "error":
        return frase_error(datos.get("clase"), datos.get("reintentar_desde") or datos.get("reinicio"))
    if tipo == "gate":
        decision = str(datos.get("decision") or "")
        if decision in ("aprobada", "aprobar"):
            return "Aprobaste"
        if decision in ("rechazada", "rechazar"):
            return "Rechazaste con un comentario"
        return "Decidiste el gate"
    return None


def frases_de_eventos(eventos, maximo: int = 60) -> list[dict]:
    """Bitácora: frases con su hora, en orden, juntando repeticiones seguidas. Deja las últimas `maximo`."""
    salida: list[dict] = []
    for e in eventos or []:
        frase = frase_evento(e.get("tipo"), e.get("datos") or {})
        if frase is None:
            continue
        if salida and salida[-1]["frase_base"] == frase:
            salida[-1]["veces"] += 1
            salida[-1]["frase"] = f"{frase} ({salida[-1]['veces']} veces)"
            salida[-1]["ts"] = e.get("ts")
        else:
            salida.append({"ts": e.get("ts"), "frase": frase, "frase_base": frase, "veces": 1})
    for entrada in salida:
        entrada.pop("frase_base", None)
    return salida[-maximo:] if maximo else salida


def _minutos_desde(desde, ahora: dt.datetime) -> int | None:
    if not desde:
        return None
    try:
        inicio = dt.datetime.fromisoformat(str(desde))
    except ValueError:
        return None
    if inicio.tzinfo is None and ahora.tzinfo is not None:
        inicio = inicio.replace(tzinfo=ahora.tzinfo)
    return max(0, int((ahora - inicio).total_seconds() // 60))


NOMBRES_AGENTE = {"cc": "Claude Code", "codex": "Codex", "cursor": "Cursor"}


def _nombre_agente(tarea: dict) -> str:
    agente = tarea.get("agente")
    return NOMBRES_AGENTE.get(agente, agente or "el agente")


def texto_estacion(tarea: dict, por_id: dict | None = None, anterior: str | None = None,
                   ahora: dt.datetime | None = None, agentes: dict | None = None,
                   desde: str | None = None) -> str:
    """Texto del estado de una estación del plan (design D6). Nunca es solo el nombre interno."""
    estado = tarea.get("estado")
    agentes = agentes or {}
    nombre = _nombre_agente(tarea)
    if estado == "hecha":
        return f"Hecha por {nombre}"
    if estado == "esperando_gate":
        return "Te espera"
    if estado == "en_curso":
        minutos = _minutos_desde(desde or tarea.get("iniciada") or tarea.get("actualizada"), ahora) if ahora else None
        return f"{nombre} trabajando hace {minutos} min" if minutos is not None else f"{nombre} trabajando"
    if estado == "bloqueada":
        por_id = por_id or {}
        abiertas = [d for d in tarea.get("dependencias") or [] if (por_id.get(d) or {}).get("estado") != "hecha"]
        if not abiertas:
            return "Bloqueada"
        dep = abiertas[0]
        return "Espera a la anterior" if dep == anterior else f"Espera a {dep}"
    if estado == "pendiente":
        info = agentes.get(tarea.get("agente")) or {}
        hasta = info.get("agotado_hasta")
        if hasta and ahora:
            try:
                fecha = dt.datetime.fromisoformat(str(hasta))
                if fecha.tzinfo is None and ahora.tzinfo is not None:
                    fecha = fecha.replace(tzinfo=ahora.tzinfo)
                if fecha > ahora:
                    return f"Plan agotado · sigue a las {_hhmm(fecha)}"
            except ValueError:
                pass
        if info and info.get("disponible") is False:
            return "Agente apagado"
        return "En cola"
    if estado == "fallida":
        clase = ((tarea.get("resultado") or {}).get("error") or {}).get("clase") or tarea.get("clase_error")
        # En las corridas el desenlace guarda clases cortas (limite/timeout/...); se aceptan tal cual.
        if clase == "seguridad":
            return "Se detuvo por seguridad"
        if clase == "violacion":
            return "Se detuvo: tocó git"
        frase = frase_error(clase, info_hasta(tarea, agentes))
        return "Falló: " + frase[0].lower() + frase[1:] if frase else "Falló"
    if estado == "cancelada":
        return "Cancelada"
    return str(estado or "")


FORMAS = {"hecha": "hecha", "en_curso": "trabajando", "esperando_gate": "espera", "bloqueada": "bloqueada",
          "fallida": "fallida", "pendiente": "pendiente", "cancelada": "cancelada"}


def forma_estacion(tarea: dict) -> str:
    return FORMAS.get(tarea.get("estado"), "pendiente")


def info_hasta(tarea: dict, agentes: dict | None = None):
    agentes = agentes or {}
    return (agentes.get(tarea.get("agente")) or {}).get("agotado_hasta")
