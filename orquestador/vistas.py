"""Vistas del estado para el tablero, la salida de Cowork y `orq estado` (solo lectura: no escriben ni corren git).

- El tablero ve todo lo de una tarea, redactado.
- La salida de Cowork se arma solo con campos de lista blanca: sin prompt (solo su hash), sin stderr ni mensajes
  de error del agente, sin salidas de comandos, sin sesiones ni códigos, con textos de 500 caracteres o menos y
  con el perfil del usuario reemplazado por `~`.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from pathlib import Path

from .comun import leer_json, sha256
from .estados import ESTADOS
from .redaccion import redactar, truncar

LARGO_COWORK = 500
HISTORIAL_COWORK = 20
EVENTOS_COWORK = 300
TOKENS = ("tokens_entrada", "tokens_salida", "tokens_cache_lectura", "tokens_cache_escritura")
CAMPOS_CONSUMO = (*TOKENS, "costo_usd", "costo_estimado", "segundos")


def huella_corta(huella: str | None) -> str | None:
    return huella[:12] if huella else None


def _fecha(texto) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(str(texto))
    except (TypeError, ValueError):
        return None


def desde_estado(t: dict) -> str | None:
    for h in reversed(t.get("historial") or []):
        if h.get("a") == t.get("estado") and h.get("de") != h.get("a"):
            return h.get("en")
    return t.get("actualizada")


def plan_agotado_hasta(t: dict, agentes: dict, ahora: dt.datetime) -> str | None:
    hasta = (agentes.get(t.get("agente")) or {}).get("agotado_hasta")
    fecha = _fecha(hasta)
    if t.get("estado") == "pendiente" and fecha and fecha > ahora:
        return hasta
    return None


def ocultar_rutas(texto: str, perfil: str | None = None) -> str:
    """Reemplaza el perfil del usuario por `~` (con barras de ambos tipos y sin distinguir mayúsculas)."""
    if not texto:
        return texto
    perfil = perfil or os.environ.get("USERPROFILE") or str(Path.home())
    for variante in {perfil, perfil.replace("\\", "/")}:
        texto = re.sub(re.escape(variante), "~", texto, flags=re.IGNORECASE)
    return texto


def texto_cowork(valor, extra=(), largo: int = LARGO_COWORK) -> str | None:
    if valor is None:
        return None
    return truncar(ocultar_rutas(redactar(str(valor), extra)), largo)


# --- tablero ---

def tarjeta(proyecto: str, t: dict, agentes: dict, ahora: dt.datetime) -> dict:
    desde = desde_estado(t)
    inicio = _fecha(desde)
    return {
        "proyecto": proyecto, "id": t["id"], "titulo": t.get("titulo"), "estado": t.get("estado"),
        "motivo": t.get("motivo"), "cambio": t.get("cambio"), "agente": t.get("agente"),
        "intentos": t.get("intentos", 0), "max_intentos": t.get("max_intentos"), "desde": desde,
        "segundos_en_estado": int((ahora - inicio).total_seconds()) if inicio else None,
        "plan_agotado_hasta": plan_agotado_hasta(t, agentes, ahora),
        "gate": {"requiere": (t.get("gate") or {}).get("requiere"),
                 "decision": (t.get("gate") or {}).get("decision"),
                 "huella_corta": huella_corta((t.get("gate") or {}).get("huella"))},
    }


def tarjetas(instantanea: dict, ahora: dt.datetime, proyecto: str | None = None,
             agente: str | None = None) -> list[dict]:
    salida = []
    for nombre, datos in sorted(instantanea.get("proyectos", {}).items()):
        if proyecto and nombre != proyecto:
            continue
        for t in datos.get("tareas", []):
            if agente and t.get("agente") != agente:
                continue
            salida.append(tarjeta(nombre, t, instantanea.get("agentes", {}), ahora))
    salida.sort(key=lambda c: (ESTADOS.index(c["estado"]) if c["estado"] in ESTADOS else 99, c["proyecto"], c["id"]))
    return salida


def leer_diffstat(carpeta_proyecto: Path, id_tarea: str) -> dict | None:
    try:
        datos = leer_json(Path(carpeta_proyecto) / "diffstat" / f"{id_tarea}.json")
    except (OSError, ValueError):
        return None
    return datos if isinstance(datos, dict) else None


def leer_informe(carpeta_proyecto: Path, id_tarea: str, maximo: int = 20000) -> str | None:
    try:
        texto = (Path(carpeta_proyecto) / "resultados" / f"{id_tarea}.md").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    return truncar(texto, maximo)


def detalle(proyecto, t: dict, agentes: dict, ahora: dt.datetime, niveles: dict | None) -> dict:
    extra = tuple(getattr(proyecto, "redactar_extra", ()) or ())
    gate = dict(t.get("gate") or {})
    gate["huella_corta"] = huella_corta(gate.get("huella"))
    resultado = t.get("resultado")
    if resultado:
        resultado = dict(resultado)
        if resultado.get("error"):
            resultado["error"] = {**resultado["error"], "mensaje": redactar(resultado["error"].get("mensaje") or "", extra)}
    corridas = [{k: c.get(k) for k in ("intento", "agente", "inicio", "fin", "ok", "clase_error", "retomada", "modelo",
                                         "duracion_s", "consumo")} for c in t.get("corridas") or []]
    diff = leer_diffstat(proyecto.carpeta, t["id"])
    return {
        **tarjeta(proyecto.nombre, t, agentes, ahora),
        "prompt": truncar(redactar(t.get("prompt") or "", extra), 4000),
        "agentes_permitidos": t.get("agentes_permitidos"), "rama": t.get("rama"), "base": t.get("base"),
        "dependencias": t.get("dependencias"), "prioridad": t.get("prioridad"),
        "interrupciones": t.get("interrupciones"), "limites_plan": t.get("limites_plan"),
        "no_antes_de": t.get("no_antes_de"), "historial": t.get("historial") or [], "corridas": corridas,
        "intento_actual": len(t.get("corridas") or []), "resultado": resultado, "consumo": t.get("consumo") or {},
        "gate": gate, "diffstat": diff, "diff_disponible": diff is not None,
        "informe": leer_informe(proyecto.carpeta, t["id"]), "niveles": niveles,
    }


def consumo(instantanea: dict, ahora: dt.datetime, proyecto: str | None = None, desde: str | None = None,
            hasta: str | None = None) -> list[dict]:
    """Por agente: tareas, intentos, tiempo, tokens, costo (o "sin costo informado"), límites y próximo reinicio."""
    acumulado: dict[str, dict] = {}
    for nombre, datos in instantanea.get("proyectos", {}).items():
        if proyecto and nombre != proyecto:
            continue
        for t in datos.get("tareas", []):
            for c in t.get("corridas") or []:
                dia = (c.get("inicio") or "")[:10]
                if (desde and dia < desde) or (hasta and dia > hasta):
                    continue
                agente = c.get("agente") or t.get("agente")
                a = acumulado.setdefault(agente, {"agente": agente, "tareas": set(), "intentos": 0, "segundos": 0.0,
                                                  **{k: 0 for k in TOKENS}, "costo_usd": None,
                                                  "costo_estimado": False, "limites": 0})
                a["tareas"].add((nombre, t["id"]))
                a["intentos"] += 1
                a["segundos"] += c.get("duracion_s") or 0
                gasto = c.get("consumo") or {}
                for k in TOKENS:
                    a[k] += gasto.get(k) or 0
                if gasto.get("costo_usd") is not None:
                    a["costo_usd"] = round((a["costo_usd"] or 0) + gasto["costo_usd"], 6)
                    a["costo_estimado"] = a["costo_estimado"] or bool(gasto.get("costo_estimado"))
                if c.get("clase_error") == "limite":
                    a["limites"] += 1
    salida = []
    for agente, a in sorted(acumulado.items()):
        a["tareas"] = len(a["tareas"])
        a["segundos"] = round(a["segundos"], 1)
        if a["costo_usd"] is None:
            a["costo_texto"] = "sin costo informado"
        else:
            a["costo_texto"] = f"{a['costo_usd']:.4f} USD" + (" (estimado)" if a["costo_estimado"] else "")
        reinicio = (instantanea.get("agentes", {}).get(agente) or {}).get("agotado_hasta")
        a["proximo_reinicio"] = reinicio if (_fecha(reinicio) and _fecha(reinicio) > ahora) else None
        salida.append(a)
    return salida


# --- salida de Cowork ---

def tarea_cowork(t: dict, extra=()) -> dict:
    gate = t.get("gate") or {}
    r = t.get("resultado")
    resultado = None
    if r:
        resultado = {"ok": r.get("ok"), "resumen": texto_cowork(r.get("resumen"), extra),
                     "error_clase": (r.get("error") or {}).get("clase"), "duracion_s": r.get("duracion_s")}
    historial = []
    for h in (t.get("historial") or [])[-HISTORIAL_COWORK:]:
        entrada = {k: h.get(k) for k in ("de", "a", "por", "via", "en")}
        entrada["motivo"] = texto_cowork(h.get("motivo"), extra)
        if h.get("huella"):
            entrada["huella_corta"] = huella_corta(h["huella"])
        historial.append(entrada)
    return {
        "id": t["id"], "titulo": texto_cowork(t.get("titulo"), extra), "estado": t.get("estado"),
        "motivo": texto_cowork(t.get("motivo"), extra), "agente": t.get("agente"),
        "agentes_permitidos": t.get("agentes_permitidos"), "cambio": t.get("cambio"), "rama": t.get("rama"),
        "base": t.get("base"), "dependencias": t.get("dependencias"), "prioridad": t.get("prioridad"),
        "intentos": t.get("intentos"), "max_intentos": t.get("max_intentos"),
        "interrupciones": t.get("interrupciones"), "limites_plan": t.get("limites_plan"),
        "no_antes_de": t.get("no_antes_de"),
        "prompt_sha256": sha256((t.get("prompt") or "").encode("utf-8")),
        "gate": {"requiere": gate.get("requiere"), "decision": gate.get("decision"),
                 "nota": texto_cowork(gate.get("nota"), extra), "en": gate.get("en"), "via": gate.get("via"),
                 "huella_corta": huella_corta(gate.get("huella"))},
        "resultado": resultado,
        "consumo": {a: {k: v.get(k) for k in CAMPOS_CONSUMO if k in v} for a, v in (t.get("consumo") or {}).items()},
        "creada": t.get("creada"), "actualizada": t.get("actualizada"), "iniciada": t.get("iniciada"),
        "terminada": t.get("terminada"), "historial": historial,
    }


def estado_cowork(proyecto: str, tareas: list[dict], agentes: dict, latido: str, extra=()) -> dict:
    return {
        "version": 1, "proyecto": proyecto, "latido": latido,
        "agentes": {n: {"disponible": a.get("disponible"), "version": a.get("version"),
                        "motivo": texto_cowork(a.get("motivo")), "agotado_hasta": a.get("agotado_hasta")}
                    for n, a in sorted(agentes.items())},
        "tareas": [tarea_cowork(t, extra) for t in tareas],
    }


_EVENTO_COWORK = {
    "inicio": ("modelo", "retomada", "version", "niveles"),
    "mensaje": ("texto",),
    "herramienta": ("nombre", "objetivo", "estado"),
    "archivo": ("ruta", "accion"),
    "comando": ("comando", "estado", "codigo_salida"),
    "fin": ("ok", "duracion_s", "consumo", "eventos_ignorados", "eventos_omitidos"),
    "error": ("clase", "reintentar_desde"),  # sin `mensaje`: puede traer el final del stderr
    "gate": ("decision", "via"),
}


def evento_cowork(e: dict, extra=()) -> dict | None:
    campos = _EVENTO_COWORK.get(e.get("tipo"))
    if campos is None:
        return None
    datos = {}
    for k in campos:
        if k not in (e.get("datos") or {}):
            continue
        v = e["datos"][k]
        datos[k] = texto_cowork(v, extra) if isinstance(v, str) else v
    if e.get("tipo") == "gate":
        datos["huella_corta"] = huella_corta((e.get("datos") or {}).get("huella"))
    return {"seq": e.get("seq"), "ts": e.get("ts"), "tarea": e.get("tarea"), "intento": e.get("intento"),
            "agente": e.get("agente"), "tipo": e.get("tipo"), "datos": datos}


def consumo_por_dia(tareas: list[dict]) -> dict:
    salida: dict[str, dict] = {}
    for t in tareas:
        for c in t.get("corridas") or []:
            dia = (c.get("inicio") or "")[:10] or "sin-fecha"
            agente = c.get("agente") or t.get("agente")
            d = salida.setdefault(agente, {}).setdefault(dia, {"intentos": 0, "segundos": 0.0, **{k: 0 for k in TOKENS},
                                                               "costo_usd": None, "costo_estimado": False,
                                                               "limites": 0})
            d["intentos"] += 1
            d["segundos"] = round(d["segundos"] + (c.get("duracion_s") or 0), 1)
            gasto = c.get("consumo") or {}
            for k in TOKENS:
                d[k] += gasto.get(k) or 0
            if gasto.get("costo_usd") is not None:
                d["costo_usd"] = round((d["costo_usd"] or 0) + gasto["costo_usd"], 6)
                d["costo_estimado"] = d["costo_estimado"] or bool(gasto.get("costo_estimado"))
            if c.get("clase_error") == "limite":
                d["limites"] += 1
    return salida


def diffstat_cowork(datos: dict) -> dict:
    archivos = [{k: a.get(k) for k in ("ruta", "agregadas", "borradas", "nuevo", "binario")}
                for a in datos.get("archivos") or [] if isinstance(a, dict)]
    return {"calculado": datos.get("calculado"), "base": datos.get("base"), "archivos": archivos,
            "total": datos.get("total")}


# --- orq estado ---

def resumen(config, proyectos) -> str:
    """Resumen de texto para `orq estado`: solo lee archivos (no toma el candado ni escribe nada)."""
    from .procesos import proceso_vivo

    lineas = []
    candado = config.raiz / "orquestador.lock"
    try:
        datos = json.loads(candado.read_text(encoding="utf-8"))
        vivo = proceso_vivo(int(datos.get("pid")), datos.get("creado"))
        lineas.append(f"Orquestador: corriendo (pid {datos.get('pid')})" if vivo else
                      "Orquestador: detenido (quedó un candado abandonado)")
    except (OSError, ValueError, TypeError):
        lineas.append("Orquestador: detenido")
    agentes = leer_json(config.raiz / "agentes.json", {}) or {}
    for nombre, info in sorted(agentes.items()):
        estado = f"disponible (versión {info.get('version')})" if info.get("disponible") else \
            f"no disponible ({info.get('motivo')})"
        if info.get("agotado_hasta"):
            estado += f", plan agotado hasta {info['agotado_hasta']}"
        lineas.append(f"Agente {nombre}: {estado}")
    for p in proyectos:
        if not p.activo:
            lineas.append(f"Proyecto {p.nombre}: inactivo ({'; '.join(p.errores)})")
            continue
        try:
            tareas = (leer_json(p.ruta_tareas, {}) or {}).get("tareas", [])
        except ValueError:
            lineas.append(f"Proyecto {p.nombre}: tareas.json ilegible")
            continue
        cuenta = {e: sum(1 for t in tareas if t.get("estado") == e) for e in ESTADOS}
        partes = [f"{n} {e}" for e, n in cuenta.items() if n]
        lineas.append(f"Proyecto {p.nombre}: " + (" · ".join(partes) if partes else "sin tareas"))
        for t in tareas:
            if t.get("estado") in ("hecha", "cancelada"):
                continue
            extra = ""
            if t.get("estado") == "esperando_gate":
                extra = f"  huella {huella_corta((t.get('gate') or {}).get('huella'))}"
            elif t.get("motivo"):
                extra = f"  ({t['motivo']})"
            lineas.append(f"  {t['id']:<12} {t.get('estado'):<15} {t.get('cambio')}  {t.get('agente')}"
                          f"  {t.get('titulo')}{extra}")
    lineas.append(f"Carpeta de Cowork: {config.cowork_raiz}")
    return "\n".join(lineas)
