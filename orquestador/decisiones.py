"""Solicitudes de Sebastian por terminal: `orq tarea <proyecto> <id> reintentar|cancelar` (spec registro-tareas).

Se dejan como archivos en `proyectos\\<p>\\decisiones\\` y el bucle de `orq correr` las aplica. Por esta vía
**nunca** se decide un gate: un archivo que lo intente se rechaza y deja un evento de seguridad.
"""
from __future__ import annotations

import json
import secrets
from pathlib import Path

from . import estados
from .comun import ID_OK, ahora, escribir_json, marca, reemplazar
from .config import Config, ErrorConfig
from .proyectos import Proyecto, cargar_proyectos
from .registro import Registro

OPERACIONES = ("reintentar", "cancelar")
CLAVES_SOLICITUD = frozenset({"op", "id", "por", "creada"})
SENALES_DE_GATE = frozenset({"aprobar", "rechazar", "gate", "decidir_gate", "aprobada", "rechazada"})


def pedir(proyecto: Proyecto, id_tarea: str, op: str) -> Path:
    if op not in OPERACIONES:
        raise ValueError(f"operación no permitida: {op} (solo {', '.join(OPERACIONES)})")
    if not ID_OK.match(id_tarea):
        raise ValueError("id de tarea inválido")
    proyecto.carpeta_decisiones.mkdir(parents=True, exist_ok=True)
    ruta = proyecto.carpeta_decisiones / f"{marca()}-{secrets.token_hex(3)}-{op}.json"
    escribir_json(ruta, {"op": op, "id": id_tarea, "por": "sebastian", "creada": ahora()})
    return ruta


def pedir_desde_cli(config: Config, nombre_proyecto: str, id_tarea: str, op: str) -> str:
    """Valida contra el registro (solo lectura) antes de dejar la solicitud, para avisar de inmediato."""
    proyecto = next((p for p in cargar_proyectos(config) if p.nombre == nombre_proyecto), None)
    if proyecto is None:
        raise ErrorConfig(f"no existe el proyecto '{nombre_proyecto}'")
    if not proyecto.activo:
        raise ErrorConfig(f"el proyecto '{nombre_proyecto}' está inactivo: {'; '.join(proyecto.errores)}")
    registro = Registro(proyecto.ruta_tareas)
    registro.cargar()
    tarea = registro.obtener(id_tarea)
    if tarea is None:
        raise ValueError(f"no existe la tarea {id_tarea} en '{nombre_proyecto}'")
    estado = tarea.get("estado")
    if op == "reintentar" and estado != "fallida":
        raise ValueError(f"solo se reintenta una tarea fallida; {id_tarea} está {estado}")
    if op == "cancelar" and estado in estados.TERMINALES:
        raise ValueError(f"{id_tarea} ya está {estado}")
    pedir(proyecto, id_tarea, op)
    return f"Solicitud '{op}' de {id_tarea} registrada; se aplica en el próximo ciclo de orq correr."


def _es_intento_de_gate(datos) -> bool:
    if not isinstance(datos, dict):
        return False
    return (str(datos.get("op", "")).lower() in SENALES_DE_GATE or "decision" in datos or "huella" in datos)


def procesar(proyecto: Proyecto, registro: Registro, momento: str | None = None, al_evento=None) -> list[dict]:
    """Aplica las solicitudes de `decisiones\\` en orden de nombre y las mueve a `decisiones\\procesadas\\`."""
    momento = momento or ahora()
    carpeta = proyecto.carpeta_decisiones
    if not carpeta.is_dir():
        return []
    procesadas = carpeta / "procesadas"
    resultados: list[dict] = []
    cambio = False
    for archivo in sorted(p for p in carpeta.glob("*.json") if p.is_file()):
        resultado = {"solicitud": archivo.name, "ok": False, "error": None}
        try:
            datos = json.loads(archivo.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError):
            datos = None
            resultado["error"] = "solicitud ilegible"
        if datos is not None:
            if _es_intento_de_gate(datos):
                resultado["error"] = "los gates solo se deciden en el tablero"
                if al_evento:
                    al_evento("error", {"clase": "seguridad",
                                        "mensaje": f"decisión de gate por archivo rechazada: {archivo.name}"},
                              tarea=datos.get("id") if isinstance(datos.get("id"), str) else None)
            elif not isinstance(datos, dict) or set(datos) - CLAVES_SOLICITUD or datos.get("op") not in OPERACIONES:
                resultado["error"] = "solicitud inválida"
            else:
                tarea = registro.obtener(str(datos.get("id")))
                if tarea is None:
                    resultado["error"] = f"no existe la tarea {datos.get('id')}"
                else:
                    try:
                        if datos["op"] == "reintentar":
                            estados.reintentar(tarea, "sebastian", "cli", momento)
                        else:
                            estados.pedir_cancelacion(tarea, "sebastian", "cli", momento)
                        resultado["ok"] = True
                        cambio = True
                    except estados.TransicionInvalida as e:
                        resultado["error"] = str(e)
        procesadas.mkdir(exist_ok=True)
        destino = procesadas / archivo.name
        if destino.exists():
            destino = procesadas / f"{archivo.stem}-{marca()}{archivo.suffix}"
        reemplazar(archivo, destino)
        escribir_json(destino.with_name(destino.stem + ".resultado.json"), resultado)
        resultados.append(resultado)
    if cambio:
        registro.guardar()
    return resultados
