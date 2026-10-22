"""Una corrida de un agente: lanzar sin ventana, leer eventos, cortar por tiempo o cancelación y cerrar.

- El proceso queda en un Job Object propio de la tarea con KILL_ON_JOB_CLOSE: al cancelar, vencer el tiempo o
  terminar, se cierra el Job y no queda vivo ningún hijo del agente.
- Si no se pudo asignar el Job, el respaldo es `taskkill /T /F`.
- De stderr se guardan solo los últimos 4 KB, redactados.
"""
from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field

from .adaptadores.base import IGNORADO, Adaptador, EstadoLectura, Lanzamiento, Resultado
from .procesos import CREATE_NO_WINDOW, Job, hora_creacion, terminar_pid
from .redaccion import redactar

TOPE_STDERR = 4096
PAUSA_S = 0.1


@dataclass
class OpcionesCorrida:
    timeout_s: float
    cancelar: threading.Event = field(default_factory=threading.Event)
    al_lanzar: object = None  # callable(pid, creado)
    al_archivo: object = None  # callable() tras cada evento `archivo`
    niveles: dict = field(default_factory=dict)
    advertencias: list = field(default_factory=list)
    patrones_extra: tuple = ()


def correr(adaptador: Adaptador, lanz: Lanzamiento, estado: EstadoLectura, escritor, tarea: str, intento: int,
           opciones: OpcionesCorrida) -> Resultado:
    for ruta, contenido in lanz.archivos.items():
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(contenido)
    inicio = time.monotonic()
    job = Job()
    proceso = subprocess.Popen(lanz.argv, cwd=str(lanz.cwd), env=lanz.env,
                               stdin=subprocess.PIPE if lanz.stdin is not None else subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                               errors="replace", creationflags=CREATE_NO_WINDOW)
    asignado = job.asignar(proceso)
    if opciones.al_lanzar:
        opciones.al_lanzar(proceso.pid, hora_creacion(proceso.pid))

    def escribir_entrada():
        try:
            proceso.stdin.write(lanz.stdin)
            proceso.stdin.close()
        except OSError:
            pass

    lineas: queue.Queue = queue.Queue()
    cola_err: deque = deque()
    largo_err = [0]

    def leer_salida():
        for linea in proceso.stdout:
            lineas.put(linea)
        lineas.put(None)

    def leer_error():
        for linea in proceso.stderr:
            cola_err.append(linea)
            largo_err[0] += len(linea)
            while largo_err[0] > 4 * TOPE_STDERR and len(cola_err) > 1:
                largo_err[0] -= len(cola_err.popleft())

    hilos = [threading.Thread(target=leer_salida, daemon=True), threading.Thread(target=leer_error, daemon=True)]
    if lanz.stdin is not None:
        hilos.append(threading.Thread(target=escribir_entrada, daemon=True))
    for h in hilos:
        h.start()

    def terminar():
        if not (asignado and job.terminar()):
            terminar_pid(proceso.pid)

    corte = None
    vigilancia = VigilanciaHerramientas(lanz.herramientas_esperadas)
    error_seguridad = None
    while True:
        if corte is None:
            if opciones.cancelar.is_set():
                corte = "cancelada"
                terminar()
            elif time.monotonic() - inicio > opciones.timeout_s:
                corte = "timeout"
                terminar()
        try:
            linea = lineas.get(timeout=PAUSA_S)
        except queue.Empty:
            continue
        if linea is None:
            break
        if corte == "seguridad":
            continue  # tras el corte no se registra ni se usa nada más de lo que diga el agente
        try:
            if corte is None:
                error_seguridad = vigilancia.revisar(linea)
            if not error_seguridad:
                _procesar_linea(adaptador, linea, estado, escritor, tarea, intento, opciones)
        except Exception as e:  # noqa: BLE001 - lo que no se puede revisar corta la corrida (falla cerrada)
            error_seguridad = f"no se pudo revisar la salida del agente ({type(e).__name__})"
        if error_seguridad:
            corte = "seguridad"
            terminar()
    try:
        proceso.wait(timeout=30)
    except subprocess.TimeoutExpired:
        terminar()
        proceso.wait(timeout=30)
    for h in hilos:
        h.join(timeout=5)
    for flujo in (proceso.stdout, proceso.stderr):
        try:
            flujo.close()
        except OSError:
            pass
    job.terminar()  # lo que el agente haya dejado corriendo no sobrevive a la corrida
    job.cerrar()
    duracion = time.monotonic() - inicio
    stderr = redactar("".join(cola_err)[-TOPE_STDERR:], opciones.patrones_extra)
    resultado = adaptador.cierre(estado, proceso.returncode, stderr, duracion)
    if corte == "seguridad":
        resultado.ok, resultado.limite = False, None
        resultado.error = {"clase": "seguridad", "mensaje": error_seguridad}
    elif corte == "timeout":
        resultado.ok, resultado.limite = False, None
        resultado.error = {"clase": "timeout", "mensaje": f"se acabó el tiempo del intento ({opciones.timeout_s:.0f} s)"}
    elif corte == "cancelada":
        resultado.ok, resultado.limite = False, None
        resultado.error = {"clase": "cancelada", "mensaje": "cancelada"}
    if resultado.error:
        escritor.escribir("error", resultado.error, tarea=tarea, intento=intento, agente=adaptador.nombre)
    escritor.escribir("fin", {"ok": resultado.ok, "duracion_s": round(duracion, 1), "consumo": resultado.consumo},
                      tarea=tarea, intento=intento, agente=adaptador.nombre)
    return resultado


class VigilanciaHerramientas:
    """Comprueba listas completas. Vigilar tool_use detecta; no garantiza ganar la carrera a la llamada."""
    def __init__(self, esperadas):
        self.esperadas = set(esperadas)
        self.vistas = None

    def revisar(self, linea):
        try:
            obj = json.loads(linea)
        except ValueError:
            return None
        if not isinstance(obj, dict):
            return None
        if obj.get("type") == "system" and obj.get("subtype") == "init":
            tools, mcp = obj.get("tools"), obj.get("mcp_servers")
            if (not isinstance(tools, list) or not all(isinstance(x, str) for x in tools)
                    or not isinstance(mcp, list) or not all(isinstance(x, dict) and isinstance(x.get("name"), str) for x in mcp)):
                return "el agente no informó sus herramientas"
            sobrantes = sorted(set(tools) - self.esperadas)
            if sobrantes or mcp:
                nombres = sobrantes + [x["name"] for x in mcp]
                return "herramientas no pedidas: " + ", ".join(nombres[:10]) + (f" ({len(nombres)-10} más)" if len(nombres)>10 else "")
            self.vistas = set(tools)
        if obj.get("type") == "assistant":
            for bloque in (obj.get("message") or {}).get("content") or []:
                if isinstance(bloque, dict) and bloque.get("type") == "tool_use":
                    nombre = bloque.get("name")
                    if self.vistas is None:
                        return "el agente no informó sus herramientas: " + str(nombre)
                    if nombre not in self.vistas:
                        return "herramientas no pedidas: " + str(nombre)
        return None


def _procesar_linea(adaptador, linea: str, estado, escritor, tarea, intento, opciones) -> None:
    linea = linea.strip()
    if not linea:
        return
    try:
        objeto = json.loads(linea)
    except ValueError:
        estado.lineas_no_json += 1
        return
    if not isinstance(objeto, dict):
        estado.lineas_no_json += 1
        return
    for tipo, datos in adaptador.normalizar(objeto, estado):
        if tipo == IGNORADO:
            escritor.ignorado(tarea, intento)
            continue
        if tipo == "inicio":
            datos = {**datos, "niveles": opciones.niveles,
                     "advertencias": [*opciones.advertencias,
                         "La vigilancia de herramientas es detección: no garantiza que la llamada no haya empezado."]}
        escritor.escribir(tipo, datos, tarea=tarea, intento=intento, agente=adaptador.nombre)
        if tipo == "archivo" and opciones.al_archivo:
            opciones.al_archivo()
