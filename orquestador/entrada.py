"""Entrada de solicitudes de Cowork (spec registro-tareas y compatibilidad-v0).

Cowork deja `*.json` en `<carpeta de Cowork>\\entrada\\` (escribe `*.tmp` y renombra). Cada solicitud se
valida completa y se aplica entera o nada. Después se mueve a `entrada\\procesadas\\` con su acuse en
`respuestas\\<mismo nombre>`. Un `.json` ilegible se reintenta durante 60 s y después va a `entrada\\rechazadas\\`.
"""
from __future__ import annotations

import copy
import json
import time
from pathlib import Path

from . import estados
from .comun import ahora, escribir_json, marca, reemplazar
from .registro import CAMPOS_COWORK, ErrorValidacion, Registro, campos_cowork, construir_tarea

OPERACIONES = ("crear", "editar", "cancelar", "reintentar")
OPERACIONES_DE_GATE = frozenset({"aprobar", "rechazar", "gate", "decidir_gate"})
ESPERA_ILEGIBLE_S = 60.0
MAX_TAREAS_POR_LOTE = 200
ESTADOS_EDITABLES = frozenset({"pendiente", "bloqueada", "fallida"})
CLAVES_V0 = frozenset({"id", "tipo", "cambio", "rama", "base", "prompt", "nueva_sesion", "timeout_min", "acciones",
                       "mensaje", "no_antes_de", "reintentos", "repo"})


class SolicitudInvalida(ValueError):
    pass


def _deps_abiertas(tarea: dict, registro: Registro, nuevas: dict[str, dict]) -> list[str]:
    abiertas = []
    for d in tarea["dependencias"]:
        dep = registro.obtener(d) or nuevas.get(d)
        if dep is None or dep.get("estado") != "hecha":
            abiertas.append(d)
    return abiertas


def _hay_ciclo(grafo: dict[str, list[str]]) -> str | None:
    """Devuelve un id que participa en un ciclo, o None."""
    color: dict[str, int] = {}

    def visitar(nodo: str) -> str | None:
        color[nodo] = 1
        for siguiente in grafo.get(nodo, []):
            if color.get(siguiente) == 1:
                return siguiente
            if color.get(siguiente) is None and siguiente in grafo:
                encontrado = visitar(siguiente)
                if encontrado:
                    return encontrado
        color[nodo] = 2
        return None

    for nodo in grafo:
        if color.get(nodo) is None:
            encontrado = visitar(nodo)
            if encontrado:
                return encontrado
    return None


def convertir_v0(trabajo: dict) -> dict:
    """Trabajo del puente v0 → datos de tarea v1. Solo `tipo: cc`; git y `repo` se rechazan."""
    desconocidas = sorted(set(trabajo) - CLAVES_V0)
    if desconocidas:
        raise SolicitudInvalida(f"trabajo v0 con claves desconocidas: {desconocidas}")
    if trabajo.get("tipo") == "git":
        raise SolicitudInvalida("las acciones de git del v0 (commit, archive, merge) no pasan al v1: "
                                "las hace Sebastian")
    if trabajo.get("repo") is not None:
        raise SolicitudInvalida("el campo 'repo' del v0 no existe en el v1: cada repo es un proyecto")
    if trabajo.get("tipo") != "cc":
        raise SolicitudInvalida("tipo de trabajo v0 desconocido (solo 'cc')")
    datos = {"id": trabajo.get("id"), "titulo": f"Trabajo v0 {trabajo.get('id')}", "prompt": trabajo.get("prompt"),
             "agente": "cc", "agentes_permitidos": ["cc"], "cambio": trabajo.get("cambio"),
             "gate": {"requiere": False}}
    for campo in ("rama", "base", "nueva_sesion", "timeout_min", "no_antes_de"):
        if trabajo.get(campo) is not None:
            datos[campo] = trabajo[campo]
    return datos


class ProcesadorEntrada:
    def __init__(self, proyecto, registro: Registro, config, reloj=time.monotonic, momento=ahora, al_evento=None):
        self.proyecto = proyecto
        self.registro = registro
        self.config = config
        self.reloj = reloj
        self.momento = momento
        self.al_evento = al_evento
        self._ilegibles: dict[str, float] = {}

    @property
    def carpeta(self) -> Path:
        return self.proyecto.carpeta_cowork

    def procesar(self) -> list[dict]:
        entrada = self.carpeta / "entrada"
        if not entrada.is_dir():
            return []
        acuses = []
        for archivo in sorted(p for p in entrada.iterdir() if p.is_file() and p.suffix.lower() == ".json"):
            try:
                datos = json.loads(archivo.read_text(encoding="utf-8"))
            except (OSError, ValueError, UnicodeDecodeError):
                primera = self._ilegibles.setdefault(archivo.name, self.reloj())
                if self.reloj() - primera < ESPERA_ILEGIBLE_S:
                    continue  # quizá Cowork todavía lo está escribiendo: se reintenta en el próximo ciclo
                self._ilegibles.pop(archivo.name, None)
                acuse = self._acuse(archivo.name, False, "v1", None, [], ["JSON ilegible por más de 60 segundos"])
                self._mover(archivo, entrada / "rechazadas")
                acuses.append(acuse)
                continue
            self._ilegibles.pop(archivo.name, None)
            acuses.append(self._procesar_una(archivo, datos))
            self._mover(archivo, entrada / "procesadas")
        return acuses

    # --- una solicitud ---

    def _procesar_una(self, archivo: Path, datos) -> dict:
        momento = self.momento()
        formato, op, ids = "v1", None, []
        foto = copy.deepcopy(self.registro.tareas)
        try:
            if not isinstance(datos, dict):
                raise SolicitudInvalida("la solicitud debe ser un objeto JSON")
            if "op" not in datos and "tipo" in datos:
                formato, op = "v0", "crear"
                datos = {"op": "crear", "tareas": [convertir_v0(datos)]}
            op = datos.get("op")
            if isinstance(op, str) and op.lower() in OPERACIONES_DE_GATE or "decision" in datos:
                if self.al_evento:
                    self.al_evento("error", {"clase": "seguridad", "mensaje":
                                             f"Cowork pidió decidir un gate ({archivo.name}); solo Sebastian lo "
                                             "decide en el tablero"}, tarea=datos.get("id"))
                raise SolicitudInvalida("Cowork no puede aprobar ni rechazar gates")
            if op == "crear":
                ids = self._crear(datos, momento)
            elif op == "editar":
                ids = [self._editar(datos, momento)]
            elif op == "cancelar":
                ids = [self._cancelar(datos, momento)]
            elif op == "reintentar":
                ids = [self._reintentar(datos, momento)]
            else:
                raise SolicitudInvalida(f"operación desconocida: {op}")
            self.registro.guardar()
            return self._acuse(archivo.name, True, formato, op, ids, [])
        except (SolicitudInvalida, ErrorValidacion, estados.TransicionInvalida) as e:
            self.registro.tareas = foto  # todo o nada: se descarta cualquier cambio a medias en memoria
            return self._acuse(archivo.name, False, formato, op, [], [str(e)])

    def _crear(self, datos: dict, momento: str) -> list[str]:
        if set(datos) - {"op", "tareas"}:
            raise SolicitudInvalida("una solicitud 'crear' solo lleva 'op' y 'tareas'")
        lote = datos.get("tareas")
        if not isinstance(lote, list) or not lote:
            raise SolicitudInvalida("'tareas' debe ser una lista no vacía")
        if len(lote) > MAX_TAREAS_POR_LOTE:
            raise SolicitudInvalida(f"un lote admite hasta {MAX_TAREAS_POR_LOTE} tareas")
        nuevas: dict[str, dict] = {}
        errores = []
        for i, d in enumerate(lote):
            try:
                t = construir_tarea(d, self.proyecto, self.config.agentes, momento)
            except ErrorValidacion as e:
                errores.append(f"tarea {i + 1}: {e}")
                continue
            if t["id"] in nuevas or self.registro.existe(t["id"]):
                errores.append(f"id repetido: {t['id']}")
                continue
            nuevas[t["id"]] = t
        if errores:
            raise SolicitudInvalida("; ".join(errores))
        for t in nuevas.values():
            for dep in t["dependencias"]:
                if dep not in nuevas and not self.registro.existe(dep):
                    raise SolicitudInvalida(f"{t['id']} depende de una tarea que no existe: {dep}")
        grafo = {t["id"]: t["dependencias"] for t in self.registro.lista()}
        grafo.update({i: t["dependencias"] for i, t in nuevas.items()})
        ciclo = _hay_ciclo(grafo)
        if ciclo:
            raise SolicitudInvalida(f"las dependencias forman un ciclo (pasa por {ciclo})")
        for t in nuevas.values():
            estados.crear(t, "cowork", momento, _deps_abiertas(t, self.registro, nuevas), via="entrada")
            self.registro.agregar(t)
        return list(nuevas)

    def _tarea_de(self, datos: dict) -> dict:
        tarea = self.registro.obtener(str(datos.get("id")))
        if tarea is None:
            raise SolicitudInvalida(f"no existe la tarea {datos.get('id')}")
        return tarea

    def _editar(self, datos: dict, momento: str) -> str:
        if set(datos) - {"op", "id", "cambios"}:
            raise SolicitudInvalida("una solicitud 'editar' solo lleva 'op', 'id' y 'cambios'")
        tarea = self._tarea_de(datos)
        cambios = datos.get("cambios")
        if not isinstance(cambios, dict) or not cambios:
            raise SolicitudInvalida("'cambios' debe ser un objeto no vacío")
        if "id" in cambios:
            raise SolicitudInvalida("el id de una tarea no se puede cambiar")
        if tarea["estado"] == "en_curso":
            raise SolicitudInvalida("la tarea está en curso")
        if tarea["estado"] not in ESTADOS_EDITABLES:
            raise SolicitudInvalida(f"no se puede editar una tarea {tarea['estado']}")
        combinado = {**campos_cowork(tarea), **cambios}
        validada = construir_tarea(combinado, self.proyecto, self.config.agentes, tarea["creada"])
        for dep in validada["dependencias"]:
            if not self.registro.existe(dep):
                raise SolicitudInvalida(f"{tarea['id']} depende de una tarea que no existe: {dep}")
        grafo = {t["id"]: t["dependencias"] for t in self.registro.lista()}
        grafo[tarea["id"]] = validada["dependencias"]
        ciclo = _hay_ciclo(grafo)
        if ciclo:
            raise SolicitudInvalida(f"las dependencias forman un ciclo (pasa por {ciclo})")
        for campo in CAMPOS_COWORK - {"id", "gate"}:
            tarea[campo] = validada[campo]
        tarea["gate"]["requiere"] = validada["gate"]["requiere"]
        tarea["gate"]["motivo"] = validada["gate"]["motivo"]
        tarea["actualizada"] = momento
        abiertas = _deps_abiertas(tarea, self.registro, {})
        if tarea["estado"] == "pendiente" and abiertas:
            estados.transicion(tarea, "bloqueada", "orquestador", "edición agrega dependencias abiertas: "
                               + ", ".join(abiertas), momento)
            tarea["motivo"] = "dependencias abiertas: " + ", ".join(abiertas)
        elif tarea["estado"] == "bloqueada" and not abiertas:
            estados.transicion(tarea, "pendiente", "orquestador", "edición deja las dependencias cumplidas", momento)
            tarea["motivo"] = None
        return tarea["id"]

    def _cancelar(self, datos: dict, momento: str) -> str:
        if set(datos) - {"op", "id"}:
            raise SolicitudInvalida("una solicitud 'cancelar' solo lleva 'op' e 'id'")
        tarea = self._tarea_de(datos)
        estados.pedir_cancelacion(tarea, "cowork", "entrada", momento)
        return tarea["id"]

    def _reintentar(self, datos: dict, momento: str) -> str:
        if set(datos) - {"op", "id"}:
            raise SolicitudInvalida("una solicitud 'reintentar' solo lleva 'op' e 'id'")
        tarea = self._tarea_de(datos)
        estados.reintentar(tarea, "cowork", "entrada", momento)
        return tarea["id"]

    # --- archivos ---

    def _acuse(self, nombre: str, ok: bool, formato: str, op, ids: list[str], errores: list[str]) -> dict:
        acuse = {"solicitud": nombre, "ok": ok, "formato": formato, "op": op, "ids": ids, "errores": errores,
                 "procesada_en": self.momento()}
        respuestas = self.carpeta / "respuestas"
        respuestas.mkdir(parents=True, exist_ok=True)
        escribir_json(respuestas / nombre, acuse)
        return acuse

    @staticmethod
    def _mover(archivo: Path, carpeta: Path) -> None:
        carpeta.mkdir(parents=True, exist_ok=True)
        destino = carpeta / archivo.name
        if destino.exists():
            destino = carpeta / f"{archivo.stem}-{marca()}{archivo.suffix}"
        reemplazar(archivo, destino)
