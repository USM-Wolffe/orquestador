"""Bucle del orquestador (spec planificacion-ejecucion, seguridad-agentes y registro-tareas).

En cada ciclo:
1. Lee `decisiones\\` y la entrada de Cowork; sus eventos de seguridad van al registro de eventos.
2. Aplica los mensajes de las corridas.
3. Pide las cancelaciones.
4. Recalcula los bloqueos.
5. Lanza lo que cabe.
6. Guarda, publica la instantánea que lee el tablero y reescribe la salida de Cowork.

Entre los pasos 1 y 2 atiende la cola en memoria de los gates del tablero: revisa el estado de la tarea, recalcula
la huella con git y, según el paso, imprime el código en la terminal o aplica la decisión.

Cada corrida vive en un hilo: prepara el worktree, revisa la seguridad, toma la foto de git, lanza al agente,
audita, calcula el diff stat y la huella, y avisa al bucle por una cola. Solo el hilo del bucle escribe
`tareas.json`.
"""
from __future__ import annotations

import copy
import datetime as dt
import os
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import decisiones, estados, procesos, seguridad, vistas, worktrees
from . import git as gitmod
from .adaptadores import adaptadores_de
from .adaptadores.base import ContextoLanzamiento, EstadoLectura, Resultado, verificar_version
from .comun import escribir_json, leer_json, normalizar, registrar
from .corrida import OpcionesCorrida, correr
from .entrada import ProcesadorEntrada
from .eventos import EscritorEventos, LectorEventos
from .gates import Gates, Peticion
from .redaccion import redactar
from .registro import Registro
from .salida_cowork import SalidaCowork
from .sesiones import Sesiones

ESPERA_LIMITE_SIN_HORA = dt.timedelta(minutes=30)
MAX_LIMITES_PLAN = 7
MAX_INTERRUPCIONES = 2
INTERVALO_DIFFSTAT_S = 10.0
ESTADOS_QUE_OCUPAN_EL_CAMBIO = frozenset({"en_curso", "esperando_gate"})
REGLAS = ("Reglas del orquestador: trabaja solo dentro de esta carpeta; no hagas commit, push, reset, checkout, "
          "switch, restore ni stash; no leas credenciales ni archivos .env; no instales paquetes. Si te niegan un "
          "permiso, anótalo en tu respuesta con su texto exacto.")


@dataclass
class EstadoProyecto:
    proyecto: object
    registro: Registro
    escritor: EscritorEventos
    entrada: ProcesadorEntrada
    sesiones: Sesiones
    sucio: bool = False

    def al_evento(self, tipo, datos, tarea=None):
        self.escritor.escribir(tipo, datos, tarea=tarea)


@dataclass
class Desenlace:
    clase: str  # ok | error | limite | seguridad | violacion | timeout | cancelada | worktree | orquestador
    mensaje: str | None = None
    resultado: Resultado | None = None
    huella: str | None = None


@dataclass
class ControlCorrida:
    proyecto: str
    id: str
    agente: str
    cambio: str
    cancelar: threading.Event = field(default_factory=threading.Event)
    hilo: threading.Thread | None = None


def componer_prompt(tarea: dict, proyecto) -> str:
    partes = [f"# Tarea {tarea['id']} · proyecto {proyecto.nombre} · cambio {tarea['cambio']}", REGLAS, "",
              tarea["prompt"]]
    avisos = []
    gate = tarea.get("gate") or {}
    if gate.get("decision") == "rechazada" and gate.get("nota"):
        avisos.append(f"Sebastian rechazó el resultado anterior: {gate['nota']}")
    if tarea.get("aviso_interrupcion"):
        avisos.append("La ejecución anterior se interrumpió. Revisa `git status` antes de seguir.")
    if avisos:
        partes += ["", "## Avisos", *[f"- {a}" for a in avisos]]
    return "\n".join(partes) + "\n"


def _sumar_consumo(acumulado: dict, nuevo: dict) -> dict:
    total = dict(acumulado)
    for clave, valor in (nuevo or {}).items():
        if clave == "costo_estimado":
            total[clave] = bool(total.get(clave)) or bool(valor)
        elif isinstance(valor, (int, float)) and not isinstance(valor, bool):
            total[clave] = round((total.get(clave) or 0) + valor, 6)
        else:
            total.setdefault(clave, None)
    return total


class Orquestador:
    def __init__(self, contexto, reloj=None, atar: bool = False, entorno: dict | None = None, terminal=None,
                 codigo_modificado: list[str] | None = None, permitir_codigo_modificado: bool = False):
        self.ctx = contexto
        self.config = contexto.config
        self.reloj = reloj or (lambda: dt.datetime.now().astimezone())
        self.atar = atar
        self.entorno_base = dict(os.environ if entorno is None else entorno)
        self.terminal = terminal or (lambda texto: print(texto, flush=True))
        # codigo_modificado None = no se revisó la integridad: los gates quedan deshabilitados (decisión 23).
        self.gates = Gates(terminal=self.terminal, codigo_modificado=codigo_modificado,
                           permitir_modificado=permitir_codigo_modificado)
        self.adaptadores = adaptadores_de(self.config)
        self.cola: queue.Queue = queue.Queue()
        self.en_curso: dict[tuple[str, str], ControlCorrida] = {}
        self.parando = False
        self.ruta_agentes = self.config.raiz / "agentes.json"
        self.agentes: dict[str, dict] = leer_json(self.ruta_agentes, {}) or {}
        self.proyectos: dict[str, EstadoProyecto] = {}
        self.salidas: dict[str, SalidaCowork] = {}
        self.lectores: dict[str, LectorEventos] = {}
        self._instantanea: dict = {"momento": None, "agentes": {}, "proyectos": {}}
        self._lock_instantanea = threading.Lock()
        for p in contexto.activos:
            registro = Registro(p.ruta_tareas)
            for aviso in registro.cargar():
                self.log(f"proyecto '{p.nombre}': {aviso}")
            escritor = EscritorEventos.para_proyecto(self.config, p)
            ep = EstadoProyecto(p, registro, escritor, None, Sesiones(p.carpeta / "sesiones.json"))
            ep.entrada = ProcesadorEntrada(p, registro, self.config, momento=self.momento, al_evento=ep.al_evento)
            self.proyectos[p.nombre] = ep
            self.salidas[p.nombre] = SalidaCowork(p)
            self.lectores[p.nombre] = LectorEventos(p.carpeta_eventos)

    # --- utilidades ---

    def momento(self) -> str:
        return self.reloj().isoformat(timespec="seconds")

    def log(self, texto: str) -> None:
        registrar(self.config.raiz, texto)

    def _guardar_agentes(self) -> None:
        escribir_json(self.ruta_agentes, self.agentes)

    def _entorno(self, proyecto) -> dict[str, str]:
        permitidas = set(proyecto.variables_permitidas)
        if proyecto.facturar_por_api:
            permitidas.add("ANTHROPIC_API_KEY")
        return seguridad.entorno_filtrado(self.entorno_base, permitidas)

    def _ahora_iso_vencido(self, texto: str | None) -> bool:
        if not texto:
            return True
        try:
            return dt.datetime.fromisoformat(texto) <= self.reloj()
        except ValueError:
            return True

    # --- arranque ---

    def iniciar(self) -> None:
        if self.atar and not procesos.atar_proceso_actual():
            self.log("no se pudo atar el orquestador a un Job Object; se usará taskkill como respaldo")
        for nombre, adaptador in self.adaptadores.items():
            agente = self.config.agentes[nombre]
            previo = self.agentes.get(nombre, {})
            if not agente.disponible:
                info = {"version": None, "disponible": False, "motivo": agente.motivo or "deshabilitado",
                        "advertencia": None}
            else:
                info = verificar_version(adaptador, agente.ejecutable, seguridad.entorno_filtrado(self.entorno_base))
            info["agotado_hasta"] = previo.get("agotado_hasta")
            if previo.get("uso_plan") is not None:
                info["uso_plan"] = previo.get("uso_plan")
            self.agentes[nombre] = info
            if not info["disponible"]:
                self.log(f"agente '{nombre}' no disponible: {info['motivo']}")
        self._guardar_agentes()
        for ep in self.proyectos.values():
            self._recuperar(ep)
            if ep.sucio:
                self._guardar(ep)
        aviso = self.gates.aviso_integridad
        if aviso:
            self.terminal(f"AVISO: {aviso}. " + ("Los gates funcionan porque se pidió --permitir-codigo-modificado; "
                                                 "cada decisión queda marcada en el historial."
                                                 if self.gates.permitir_modificado else
                                                 "Los gates quedan deshabilitados hasta hacer commit o arrancar con "
                                                 "--permitir-codigo-modificado."))
            self.log(f"integridad: {aviso}")
        from . import instalar as mod_instalar
        aviso_push = mod_instalar.aviso_push(self.config.git)
        if aviso_push:
            self.terminal(aviso_push)
            self.log("remoto: push por defecto habilitado")
        self._publicar()

    def _recuperar(self, ep: EstadoProyecto) -> None:
        """Tareas que quedaron `en_curso` por un corte: vuelven a `pendiente` o, con más de 2 cortes, a `fallida`."""
        momento = self.momento()
        for t in ep.registro.lista():
            if t["estado"] != "en_curso":
                continue
            ultima = t["corridas"][-1] if t.get("corridas") else {}
            pid = ultima.get("pid")
            if pid and procesos.proceso_vivo(pid, ultima.get("creado")):
                procesos.terminar_pid(pid)
                self.log(f"{ep.proyecto.nombre}/{t['id']}: se terminó el proceso {pid} que quedó de la corrida anterior")
            ultima.update(fin=momento, ok=False, clase_error="interrumpida")
            ep.sucio = True
            if t.get("cancelacion"):
                estados.ejecutar_cancelacion(t, momento)
                continue
            t["interrupciones"] = int(t.get("interrupciones", 0)) + 1
            t["intentos"] = max(0, int(t.get("intentos", 0)) - 1)
            if t["interrupciones"] > MAX_INTERRUPCIONES:
                estados.transicion(t, "fallida", "orquestador", "interrumpida demasiadas veces", momento)
                t["motivo"] = "interrumpida demasiadas veces"
            else:
                estados.transicion(t, "pendiente", "orquestador", "interrumpida", momento)
                t["motivo"] = "interrumpida"
                t["aviso_interrupcion"] = True

    # --- ciclo ---

    def ciclo(self) -> None:
        momento = self.momento()
        for ep in self.proyectos.values():
            if decisiones.procesar(ep.proyecto, ep.registro, momento, al_evento=ep.al_evento):
                ep.sucio = True
            if ep.entrada.procesar():
                ep.sucio = True
        self._atender_gates()
        self._aplicar_cola()
        self._cancelaciones()
        for ep in self.proyectos.values():
            self._recalcular_bloqueos(ep)
        self._lanzar()
        for ep in self.proyectos.values():
            if ep.sucio:
                self._guardar(ep)
        self._publicar()

    # --- instantánea para el tablero y salida de Cowork ---

    def instantanea(self) -> dict:
        """Copia del estado que publicó el último ciclo (el tablero solo lee esto, nunca el registro vivo)."""
        with self._lock_instantanea:
            return self._instantanea

    def _publicar(self) -> None:
        momento = self.momento()
        instantanea = {"momento": momento, "agentes": copy.deepcopy(self.agentes),
                       "proyectos": {n: {"tareas": copy.deepcopy(ep.registro.lista())}
                                     for n, ep in self.proyectos.items()}}
        with self._lock_instantanea:
            self._instantanea = instantanea
        for nombre, salida in self.salidas.items():
            try:
                salida.escribir(instantanea["proyectos"][nombre]["tareas"], instantanea["agentes"],
                                self.lectores[nombre].ultimos(vistas.EVENTOS_COWORK), momento)
            except OSError as e:
                self.log(f"no se pudo escribir la salida de Cowork de '{nombre}': {e}")

    # --- gates del tablero (cola en memoria) ---

    def _atender_gates(self) -> None:
        for proyecto, id_tarea, texto in self.gates.avisos_pendientes():
            ep = self.proyectos.get(proyecto)
            if ep:
                ep.escritor.escribir("error", {"clase": "seguridad", "mensaje": texto}, tarea=id_tarea)
            self.log(f"{proyecto}/{id_tarea}: {texto}")
        for peticion in self.gates.peticiones():
            try:
                estado, cuerpo = self._resolver_gate(peticion)
            except Exception as e:  # noqa: BLE001 - el tablero siempre recibe respuesta
                self.log(f"falla al atender un gate de {peticion.proyecto}/{peticion.id}: {type(e).__name__}: {e}")
                estado, cuerpo = 500, {"error": "falla interna del orquestador"}
            peticion.responder(estado, cuerpo)

    def _huella_actual(self, ep: EstadoProyecto, t: dict) -> str | None:
        wt = worktrees.ruta_worktree(ep.proyecto, t["cambio"])
        if not (wt / ".git").exists():
            return None
        informe = ep.proyecto.carpeta / "resultados" / f"{t['id']}.md"
        return gitmod.huella_estado(self.config.git, wt, t["id"], len(t.get("corridas") or []), informe)

    def _resolver_gate(self, peticion: Peticion) -> tuple[int, dict]:
        ep = self.proyectos.get(peticion.proyecto)
        t = ep.registro.obtener(peticion.id) if ep else None
        if t is None:
            return 404, {"error": "no existe la tarea"}
        if t["estado"] != "esperando_gate":
            return 409, {"error": f"la tarea no espera gate (está {t['estado']})"}
        guardada = t["gate"].get("huella")
        actual = self._huella_actual(ep, t)
        if not guardada or peticion.huella != guardada or actual != guardada:
            return 409, {"error": "el estado cambió, vuelve a revisar"}
        if peticion.paso == "preparar":
            self.gates.emitir_codigo(peticion)
            return 200, {"ok": True, "mensaje": "Escribe el código que muestra la terminal del orquestador.",
                         "vence_s": 120}
        momento = self.momento()
        marca = {"codigo_modificado": True} if self.gates.aviso_integridad else {}
        estados.decidir_gate(t, peticion.decision, "sebastian", "tablero", momento, nota=peticion.nota,
                             huella=actual, sesion=peticion.sesion, **marca)
        decision = t["gate"]["decision"]
        ep.escritor.escribir("gate", {"decision": decision, "huella": actual, "via": "tablero",
                                      "sesion": peticion.sesion}, tarea=t["id"], intento=len(t["corridas"]),
                             agente=t["agente"])
        linea = (f"[gate] {peticion.proyecto}/{t['id']} {decision} por Sebastian desde el tablero · "
                 f"huella {actual[:12]} · sesión {peticion.sesion} · {momento}")
        self.terminal(linea)
        self.log(linea)
        ep.sucio = True
        self._guardar(ep)
        return 200, {"ok": True, "estado": t["estado"], "decision": decision}

    def _guardar(self, ep: EstadoProyecto) -> None:
        for aviso in ep.registro.guardar():
            self.log(f"proyecto '{ep.proyecto.nombre}': {aviso}")
        ep.sucio = False

    def _recalcular_bloqueos(self, ep: EstadoProyecto) -> None:
        momento = self.momento()
        for t in ep.registro.lista():
            if t["estado"] not in ("pendiente", "bloqueada"):
                continue
            abiertas, fallidas = [], []
            for d in t["dependencias"]:
                dep = ep.registro.obtener(d)
                estado = dep["estado"] if dep else None
                if estado != "hecha":
                    abiertas.append(d)
                    if estado in ("fallida", "cancelada"):
                        fallidas.append(f"dependencia {d} {estado}")
            motivo = "; ".join(fallidas) if fallidas else ("dependencias abiertas: " + ", ".join(abiertas))
            if t["estado"] == "pendiente" and abiertas:
                estados.transicion(t, "bloqueada", "orquestador", motivo, momento)
                t["motivo"] = motivo
                ep.sucio = True
            elif t["estado"] == "bloqueada" and not abiertas:
                estados.transicion(t, "pendiente", "orquestador", "dependencias cumplidas", momento)
                t["motivo"] = None
                ep.sucio = True
            elif t["estado"] == "bloqueada" and t.get("motivo") != motivo:
                t["motivo"] = motivo
                ep.sucio = True

    def _cancelaciones(self) -> None:
        for (nombre, id_tarea), control in self.en_curso.items():
            t = self.proyectos[nombre].registro.obtener(id_tarea)
            if t and t.get("cancelacion"):
                control.cancelar.set()

    def _corriendo(self, agente=None, proyecto=None) -> int:
        return sum(1 for c in self.en_curso.values()
                   if (agente is None or c.agente == agente) and (proyecto is None or c.proyecto == proyecto))

    def _cambio_ocupado(self, ep: EstadoProyecto, tarea: dict) -> bool:
        return any(o["id"] != tarea["id"] and o["cambio"] == tarea["cambio"] and o["estado"] in ESTADOS_QUE_OCUPAN_EL_CAMBIO
                   for o in ep.registro.lista())

    def _poner_motivo(self, ep, t, motivo) -> None:
        if t.get("motivo") != motivo:
            t["motivo"] = motivo
            ep.sucio = True

    def _lanzar(self) -> None:
        candidatas = [(ep, t) for ep in self.proyectos.values() for t in ep.registro.lista() if t["estado"] == "pendiente"]
        candidatas.sort(key=lambda par: (par[1].get("prioridad", 100), par[1].get("creada") or ""))
        for ep, t in candidatas:
            if len(self.en_curso) >= self.config.limite_global:
                return
            agente = t["agente"]
            info = self.agentes.get(agente) or {}
            if agente not in self.adaptadores or not info.get("disponible"):
                self._poner_motivo(ep, t, f"agente no disponible: {info.get('motivo') or 'no configurado'}")
                continue
            if not self._ahora_iso_vencido(info.get("agotado_hasta")):
                self._poner_motivo(ep, t, f"plan agotado hasta {info['agotado_hasta']}")
                continue
            if not self._ahora_iso_vencido(t.get("no_antes_de")):
                continue
            if self._corriendo(agente=agente) >= self.config.limite_por_agente.get(agente, 1):
                continue
            if self._corriendo(proyecto=ep.proyecto.nombre) >= ep.proyecto.limite_global:
                continue
            tope_agente = ep.proyecto.limite_por_agente.get(agente, self.config.limite_por_agente.get(agente, 1))
            if self._corriendo(agente=agente, proyecto=ep.proyecto.nombre) >= tope_agente:
                continue
            if self._cambio_ocupado(ep, t):
                continue
            self._iniciar_corrida(ep, t)

    def _sesion_para(self, ep: EstadoProyecto, t: dict) -> tuple[str, bool]:
        guardada = ep.sesiones.obtener(t["cambio"], t["agente"])
        if guardada and not seguridad.sesion_valida(guardada):
            self.log(f"{ep.proyecto.nombre}/{t['id']}: id de sesión inválido en sesiones.json; se abre una sesión nueva")
            ep.escritor.escribir("error", {"clase": "sesion", "mensaje": "id de sesión inválido en sesiones.json"},
                                 tarea=t["id"])
            guardada = None
        if guardada and not t.get("nueva_sesion"):
            return guardada, True
        nueva = str(uuid.uuid4())
        ep.sesiones.guardar(t["cambio"], t["agente"], nueva)  # antes de lanzar
        return nueva, False

    def _iniciar_corrida(self, ep: EstadoProyecto, t: dict) -> None:
        momento = self.momento()
        sesion, retomar = self._sesion_para(ep, t)
        prompt = componer_prompt(t, ep.proyecto)
        estados.transicion(t, "en_curso", "orquestador", "hay cupo", momento)
        t["motivo"] = None
        t["intentos"] = int(t.get("intentos", 0)) + 1
        t["iniciada"] = t.get("iniciada") or momento
        t.pop("aviso_interrupcion", None)
        t["nueva_sesion"] = False
        t["gate"].update(decision=None, nota=None, en=None, huella=None, via=None)
        intento = len(t.get("corridas", [])) + 1
        t.setdefault("corridas", []).append({"intento": intento, "agente": t["agente"], "inicio": momento, "fin": None,
                                             "ok": None, "clase_error": None, "sesion": sesion, "retomada": retomar,
                                             "pid": None, "creado": None})
        ep.sucio = True
        self._guardar(ep)
        control = ControlCorrida(ep.proyecto.nombre, t["id"], t["agente"], t["cambio"])
        foto_tarea = {k: (dict(v) if isinstance(v, dict) else v) for k, v in t.items()}
        control.hilo = threading.Thread(target=self._hilo_corrida, daemon=True,
                                        args=(ep, foto_tarea, intento, sesion, retomar, prompt, control))
        self.en_curso[(ep.proyecto.nombre, t["id"])] = control
        control.hilo.start()

    # --- hilo de una corrida ---

    def _hilo_corrida(self, ep, t, intento, sesion, retomar, prompt, control) -> None:
        clave = (ep.proyecto.nombre, t["id"])
        try:
            desenlace = self._ejecutar(ep, t, intento, sesion, retomar, prompt, control)
        except Exception as e:  # noqa: BLE001 - una falla interna nunca deja la tarea en curso para siempre
            desenlace = Desenlace("orquestador", f"{type(e).__name__}: {e}")
        self.cola.put(("fin", clave, desenlace))

    def _ejecutar(self, ep, t, intento, sesion, retomar, prompt, control) -> Desenlace:
        p, adaptador, git = ep.proyecto, self.adaptadores[t["agente"]], self.config.git
        clave = (p.nombre, t["id"])
        try:
            wt = worktrees.asegurar(git, p, t["cambio"], t["rama"], t.get("base"))
        except worktrees.ErrorWorktree as e:
            ep.escritor.escribir("error", {"clase": "worktree", "mensaje": str(e)}, tarea=t["id"], intento=intento,
                                 agente=t["agente"])
            return Desenlace("worktree", str(e))
        try:
            seguridad.revisar_worktree(wt, p.huellas_aprobadas)
        except seguridad.ErrorSeguridad as e:
            ep.escritor.escribir("error", {"clase": "seguridad", "mensaje": str(e)}, tarea=t["id"], intento=intento,
                                 agente=t["agente"])
            return Desenlace("seguridad", str(e))
        desde = time.monotonic()
        antes = gitmod.foto(git, wt, t["rama"])
        carpeta_corrida = p.carpeta / "corridas" / t["id"] / str(intento)
        ultimo_diff = [0.0]

        def diff_parcial():
            if time.monotonic() - ultimo_diff[0] >= INTERVALO_DIFFSTAT_S:
                ultimo_diff[0] = time.monotonic()
                self._escribir_diffstat(p, t, wt)

        resultado = None
        for _ in range(2):  # el segundo intento solo si la sesión guardada ya no existe
            ctx = ContextoLanzamiento(tarea=t, proyecto=p, config=self.config, worktree=wt, sesion=sesion,
                                      retomar=retomar, carpeta_corrida=carpeta_corrida, entorno=self._entorno(p),
                                      prompt=prompt)
            lanz = adaptador.lanzamiento(ctx)
            try:
                seguridad.revisar_lanzamiento(adaptador, lanz, prompt)
            except seguridad.ErrorSeguridad as e:
                ep.escritor.escribir("error", {"clase": "seguridad", "mensaje": str(e)}, tarea=t["id"],
                                     intento=intento, agente=t["agente"])
                return Desenlace("seguridad", str(e))
            info = self.agentes.get(t["agente"]) or {}
            opciones = OpcionesCorrida(
                timeout_s=60.0 * (t.get("timeout_min") or p.timeout_min), cancelar=control.cancelar,
                al_lanzar=lambda pid, creado: self.cola.put(("lanzada", clave, (pid, creado))),
                al_archivo=diff_parcial, niveles=seguridad.niveles(t["agente"]),
                advertencias=[a for a in [info.get("advertencia")] if a], patrones_extra=tuple(p.redactar_extra))
            resultado = correr(adaptador, lanz, EstadoLectura(worktree=wt, retomada=retomar), ep.escritor, t["id"],
                               intento, opciones)
            if resultado.sesion_inexistente and retomar:
                ep.sesiones.borrar(t["cambio"], t["agente"])
                anterior, sesion, retomar = sesion, str(uuid.uuid4()), False
                ep.sesiones.guardar(t["cambio"], t["agente"], sesion)
                self.cola.put(("nota", clave, f"la sesión {anterior} ya no existía; se abrió la sesión {sesion}"))
                continue
            break
        despues = gitmod.foto(git, wt, t["rama"])
        # Worktrees y ramas que el orquestador creó para otra tarea del mismo repo mientras este agente corría.
        propios = worktrees.creados_entre(p.repo, desde, time.monotonic()) - {(normalizar(wt), t["rama"])}
        cambios = gitmod.diferencias(antes, despues, propios=propios)
        informe = p.carpeta / "resultados" / f"{t['id']}.md"
        informe.parent.mkdir(parents=True, exist_ok=True)
        informe.write_text(redactar(resultado.texto or "", p.redactar_extra), encoding="utf-8")
        self._escribir_diffstat(p, t, wt)
        if cambios:
            mensaje = "el agente cambió el estado de git: " + ", ".join(cambios)
            ep.escritor.escribir("error", {"clase": "violacion", "mensaje": mensaje}, tarea=t["id"], intento=intento,
                                 agente=t["agente"])
            return Desenlace("violacion", mensaje, resultado)
        if resultado.ok:
            huella = gitmod.huella_estado(git, wt, t["id"], intento, informe) if t["gate"]["requiere"] else None
            return Desenlace("ok", None, resultado, huella)
        clase = (resultado.error or {}).get("clase", "agente")
        if clase == "limite_uso":
            return Desenlace("limite", (resultado.error or {}).get("mensaje"), resultado)
        if clase in ("timeout", "cancelada", "seguridad"):
            return Desenlace(clase, (resultado.error or {}).get("mensaje"), resultado)
        return Desenlace("error", (resultado.error or {}).get("mensaje"), resultado)

    def _escribir_diffstat(self, p, t, wt) -> None:
        datos = gitmod.diffstat(self.config.git, wt, t.get("base") or p.base)
        destino = p.carpeta / "diffstat" / f"{t['id']}.json"
        destino.parent.mkdir(parents=True, exist_ok=True)
        escribir_json(destino, datos)

    # --- resultados ---

    def _aplicar_cola(self) -> None:
        while True:
            try:
                tipo, (nombre, id_tarea), datos = self.cola.get_nowait()
            except queue.Empty:
                return
            ep = self.proyectos[nombre]
            t = ep.registro.obtener(id_tarea)
            if t is None:
                continue
            if tipo == "lanzada":
                t["corridas"][-1].update(pid=datos[0], creado=datos[1])
            elif tipo == "nota":
                estados.anotar(t, "orquestador", datos, self.momento())
            elif tipo == "fin":
                control = self.en_curso.pop((nombre, id_tarea), None)
                if control and control.hilo:
                    control.hilo.join(timeout=5)
                self._aplicar_fin(ep, t, datos)
            ep.sucio = True

    def _aplicar_fin(self, ep: EstadoProyecto, t: dict, d: Desenlace) -> None:
        momento = self.momento()
        r = d.resultado
        ultima = t["corridas"][-1]
        ultima.update(fin=momento, ok=d.clase == "ok", clase_error=None if d.clase == "ok" else d.clase)
        if r is not None:
            t["consumo"][t["agente"]] = _sumar_consumo(t["consumo"].get(t["agente"], {}), r.consumo)
            ultima.update(modelo=r.modelo, consumo=dict(r.consumo or {}), duracion_s=round(r.duracion_s, 1))
            if getattr(r, "uso_plan", None) is not None:
                info = self.agentes.setdefault(t["agente"], {})
                info["uso_plan"] = dict(r.uso_plan)
                self._guardar_agentes()
        error = None if d.clase == "ok" else {"clase": d.clase, "mensaje": redactar(d.mensaje or "")[:1000]}
        t["resultado"] = {"ok": d.clase == "ok", "resumen": redactar((r.texto if r else "") or "")[:500],
                          "error": error, "codigo_salida": r.codigo_salida if r else None,
                          "sesion": r.sesion if r else ultima.get("sesion"),
                          "duracion_s": round(r.duracion_s, 1) if r else None}
        if t.get("cancelacion"):
            estados.ejecutar_cancelacion(t, momento)
            return
        if d.clase == "limite":
            t["intentos"] = max(0, int(t["intentos"]) - 1)
            t["limites_plan"] = int(t.get("limites_plan", 0)) + 1
            hasta = (r.limite.hasta if r and r.limite else None) or \
                (self.reloj() + ESPERA_LIMITE_SIN_HORA).isoformat(timespec="seconds")
            info = self.agentes.setdefault(t["agente"], {})
            if self._ahora_iso_vencido(info.get("agotado_hasta")) or (info.get("agotado_hasta") or "") < hasta:
                info["agotado_hasta"] = hasta
            self._guardar_agentes()
            if t["limites_plan"] >= MAX_LIMITES_PLAN:
                estados.transicion(t, "fallida", "orquestador", "límite de plan repetido", momento)
                t["motivo"] = "límite de plan repetido"
            else:
                estados.transicion(t, "pendiente", "orquestador", f"límite del plan hasta {hasta}", momento)
                t["no_antes_de"], t["motivo"] = hasta, f"límite del plan hasta {hasta}"
            return
        if d.clase in ("seguridad", "violacion"):
            estados.transicion(t, "fallida", "orquestador", d.mensaje or d.clase, momento)
            t["motivo"] = d.mensaje
            return
        if d.clase == "ok":
            if t["gate"]["requiere"]:
                estados.transicion(t, "esperando_gate", "orquestador", "esperando la decisión de Sebastian", momento)
                t["gate"]["huella"] = d.huella
                self.terminal(f"[gate] {ep.proyecto.nombre}/{t['id']} espera tu decisión en el tablero "
                              f"(huella {(d.huella or '')[:12]})")
            else:
                estados.transicion(t, "hecha", "orquestador", "terminó bien", momento)
            return
        if int(t["intentos"]) < int(t["max_intentos"]):
            estados.transicion(t, "pendiente", "orquestador", f"error ({d.clase}); se reintenta", momento)
            t["motivo"] = f"error en el intento anterior: {d.clase}"
        else:
            estados.transicion(t, "fallida", "orquestador", f"error ({d.clase}) sin intentos disponibles", momento)
            t["motivo"] = f"sin intentos: {d.clase}"

    # --- correr y detener ---

    def correr(self, una_vez: bool = False, parar: threading.Event | None = None) -> None:
        self.iniciar()
        parar = parar or threading.Event()
        try:
            while not parar.is_set():
                self.ciclo()
                if una_vez and not self.en_curso:
                    break
                parar.wait(self.config.intervalo_s)
        finally:
            self.detener()

    def detener(self) -> None:
        """Corta las corridas en curso como lo haría un apagón: las tareas quedan `en_curso` y el próximo inicio las
        recupera como interrumpidas."""
        self.parando = True
        for control in list(self.en_curso.values()):
            control.cancelar.set()
        for control in list(self.en_curso.values()):
            if control.hilo:
                control.hilo.join(timeout=30)
        self.en_curso.clear()
        while not self.cola.empty():
            tipo, (nombre, id_tarea), datos = self.cola.get_nowait()
            if tipo == "lanzada":
                t = self.proyectos[nombre].registro.obtener(id_tarea)
                if t:
                    t["corridas"][-1].update(pid=datos[0], creado=datos[1])
                    self.proyectos[nombre].sucio = True
        for ep in self.proyectos.values():
            if ep.sucio:
                self._guardar(ep)
