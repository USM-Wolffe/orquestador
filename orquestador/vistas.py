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

from . import frases
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


_VEREDICTOS = {"sin reparos": "sin_reparos", "con reparos": "con_reparos", "no concluyente": "no_concluyente"}
NOMBRES_AGENTE = frases.NOMBRES_AGENTE


def veredicto_revision(informe: str | None) -> tuple[str, str | None]:
    """Veredicto de la primera línea del informe y resumen de los 500 caracteres siguientes (redactados)."""
    if not informe:
        return "no_concluyente", None
    primera, _, resto = informe.partition("\n")
    m = re.match(r"\s*Veredicto:\s*(sin reparos|con reparos|no concluyente)\s*\.?\s*$", primera, re.IGNORECASE)
    if not m:
        return "no_concluyente", truncar(redactar(informe.strip()), 500) or None
    resumen = truncar(redactar(resto.strip()), 500)
    return _VEREDICTOS[m.group(1).lower()], resumen or None


def _buscar_mapa(mapa, proyecto: str, id_tarea: str):
    if not mapa:
        return None
    if (proyecto, id_tarea) in mapa:
        return mapa[(proyecto, id_tarea)]
    return mapa.get(id_tarea)


def _orden_topologico(tareas: list[dict]) -> list[dict]:
    por_id = {t["id"]: t for t in tareas}
    restantes = list(tareas)
    salida, vistos = [], set()
    while restantes:
        listas = [t for t in restantes
                  if all(d not in por_id or d in vistos for d in t.get("dependencias") or [])]
        if not listas:  # ciclo o dependencia rota: se sigue por fecha e id, sin perder tareas
            listas = restantes
        listas.sort(key=lambda t: (t.get("creada") or "", t["id"]))
        elegida = listas[0]
        salida.append(elegida)
        vistos.add(elegida["id"])
        restantes.remove(elegida)
    return salida


def tablero(instantanea: dict, ahora: dt.datetime, proyecto: str | None = None, *, diffstats=None,
            informes=None, eventos=None, gates=None) -> dict:
    """Datos de la página principal (design D4): turno, agentes y plan, sin prompt y con textos redactados."""
    proyectos_datos = instantanea.get("proyectos", {}) or {}
    nombres = sorted(proyectos_datos)
    seleccion = proyecto if proyecto in proyectos_datos else None
    alcance = [seleccion] if seleccion else nombres
    agentes_info = instantanea.get("agentes", {}) or {}

    # --- Te toca decidir ---
    turno = []
    for nombre in alcance:
        tareas = proyectos_datos[nombre].get("tareas", [])
        por_id = {t["id"]: t for t in tareas}
        for t in tareas:
            if t.get("estado") != "esperando_gate":
                continue
            revisada = por_id.get(t.get("revisa")) if t.get("revisa") else None
            diff = _buscar_mapa(diffstats, nombre, t["id"])
            archivos = 0
            if isinstance(diff, dict):
                total = diff.get("total")
                archivos = total.get("archivos", 0) if isinstance(total, dict) else len(diff.get("archivos") or [])
            pruebas = None
            for e in reversed(_buscar_mapa(eventos, nombre, t["id"]) or []):
                d = e.get("datos") or {}
                if e.get("tipo") == "comando" and ("unittest" in str(d.get("comando") or "")
                                                  or "pytest" in str(d.get("comando") or "")) \
                        and d.get("estado") in ("ok", "error"):
                    pruebas = {"ok": d.get("estado") == "ok", "en": e.get("ts")}
                    break
            revision = None
            rev_tarea = t if t.get("revisa") else next((x for x in tareas if x.get("revisa") == t["id"]), None)
            if rev_tarea is not None:
                veredicto, resumen = veredicto_revision(_buscar_mapa(informes, nombre, rev_tarea["id"]))
                revision = {"veredicto": veredicto, "resumen": resumen, "agente": rev_tarea.get("agente")}
            explicacion = (revisada or {}).get("explicacion") or t.get("explicacion")
            turno.append({"id": t["id"], "proyecto": nombre,
                          "titulo": redactar((revisada or t).get("titulo") or ""),
                          "explicacion": redactar(explicacion) if explicacion else None,
                          "archivos": archivos, "pruebas": pruebas, "revision": revision})

    # --- Ahora mismo ---
    agentes = []
    hoy = ahora.date()
    for agente in sorted(agentes_info):
        info = agentes_info[agente] or {}
        tareas_agente = [t for n in alcance for t in proyectos_datos[n].get("tareas", []) if t.get("agente") == agente]
        en_curso = next((t for t in tareas_agente if t.get("estado") == "en_curso"), None)
        frase = frase_en = None
        if en_curso is not None:
            bitacora = frases.frases_de_eventos(_eventos_de(eventos, alcance, proyectos_datos, en_curso))
            if bitacora:
                frase, frase_en = bitacora[-1]["frase"], bitacora[-1]["ts"]
        segundos_hoy, tareas_hoy = 0.0, set()
        for t in tareas_agente:
            for c in t.get("corridas") or []:
                inicio = _fecha(c.get("inicio"))
                if inicio is None or inicio.date() != hoy:
                    continue
                tareas_hoy.add(t["id"])
                if c.get("duracion_s") is not None:
                    segundos_hoy += c.get("duracion_s") or 0
                elif _fecha(c.get("fin")):
                    segundos_hoy += (_fecha(c.get("fin")) - inicio).total_seconds()
                elif t.get("estado") == "en_curso":
                    segundos_hoy += max(0.0, (ahora - inicio).total_seconds())
        agotado = info.get("agotado_hasta")
        fecha_agotado = _fecha(agotado)
        if en_curso is not None:
            estado_ag, motivo, reinicio, titulo_tarea = "trabajando", None, None, en_curso.get("titulo")
        elif fecha_agotado and fecha_agotado > ahora:
            estado_ag, reinicio = "plan_agotado", agotado
            motivo, titulo_tarea = f"Plan agotado · sigue a las {fecha_agotado.strftime('%H:%M')}", None
        elif info.get("disponible") is False:
            estado_ag, motivo, reinicio, titulo_tarea = "apagado", info.get("motivo") or "Agente apagado", None, None
        else:
            estado_ag, motivo, reinicio, titulo_tarea = "disponible", None, None, None
        uso_plan = info.get("uso_plan") if isinstance(info.get("uso_plan"), dict) else {}
        uso = uso_plan.get("uso")
        agentes.append({"agente": agente, "nombre": NOMBRES_AGENTE.get(agente, agente), "estado": estado_ag,
                        "tarea": titulo_tarea, "frase": frase, "frase_en": frase_en, "motivo": motivo,
                        "reinicio": reinicio,
                        "hoy": {"minutos": int(segundos_hoy // 60), "tareas": len(tareas_hoy)},
                        "plan": {"uso": uso, "visto_en": uso_plan.get("visto_en") if uso is not None else None}})

    # --- El plan ---
    plan = []
    corte = ahora - dt.timedelta(hours=24)
    for nombre in alcance:
        tareas = proyectos_datos[nombre].get("tareas", [])
        por_id = {t["id"]: t for t in tareas}
        por_cambio: dict[str, list[dict]] = {}
        for t in tareas:
            por_cambio.setdefault(t.get("cambio"), []).append(t)
        for cambio in sorted(por_cambio, key=lambda c: str(c)):
            grupo = por_cambio[cambio]
            sin_terminar = any(t.get("estado") not in ("hecha", "cancelada") for t in grupo)
            reciente = any((_fecha(t.get("terminada") or t.get("actualizada")) or dt.datetime.min.replace(tzinfo=ahora.tzinfo)) >= corte
                           for t in grupo)
            if not (sin_terminar or reciente):
                continue
            orden = _orden_topologico(grupo)
            estaciones, anterior = [], None
            for t in orden:
                estaciones.append({"id": t["id"], "titulo": redactar(t.get("titulo") or ""), "agente": t.get("agente"),
                                   "forma": frases.forma_estacion(t),
                                   "texto": frases.texto_estacion(t, por_id, anterior=anterior, ahora=ahora,
                                                                  agentes=agentes_info,
                                                                  desde=desde_estado(t))})
                anterior = t["id"]
            listas_c = sum(1 for t in grupo if t.get("estado") == "hecha")
            nota = None
            for i, t in enumerate(orden):
                if t.get("estado") == "esperando_gate":
                    nota = f"termina cuando apruebes la {i + 1}"
                    break
            if nota is None and listas_c == len(grupo):
                nota = "todas listas"
            plan.append({"proyecto": nombre, "cambio": cambio, "listas": listas_c, "total": len(grupo),
                         "nota": nota, "estaciones": estaciones})

    return {"momento": instantanea.get("momento"), "proyecto": seleccion, "proyectos": nombres,
            "gates": gates if gates is not None else {"deshabilitados": None},
            "turno": turno, "agentes": agentes, "plan": plan}


def _eventos_de(eventos, alcance, proyectos_datos, tarea):
    for nombre in alcance:
        if any(t["id"] == tarea["id"] for t in proyectos_datos[nombre].get("tareas", [])):
            return _buscar_mapa(eventos, nombre, tarea["id"]) or []
    return []


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
