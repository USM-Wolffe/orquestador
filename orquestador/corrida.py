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
        _procesar_linea(adaptador, linea, estado, escritor, tarea, intento, opciones)
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
    if corte == "timeout":
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
            datos = {**datos, "niveles": opciones.niveles, "advertencias": opciones.advertencias}
        escritor.escribir(tipo, datos, tarea=tarea, intento=intento, agente=adaptador.nombre)
        if tipo == "archivo" and opciones.al_archivo:
            opciones.al_archivo()
