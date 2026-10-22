"""Registro de tareas por proyecto (spec registro-tareas).

- `tareas.json` es la fuente de verdad y solo lo escribe `orq correr`.
- La escritura es atómica: primero `tareas.json.tmp`, después `.bak` con la versión previa, y al final el
  reemplazo, con reintentos si Windows lo traba.
- Detecta escrituras externas comparando la huella de lo último que escribió.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from .comun import BASE_OK, ID_OK, NOMBRE_OK, a_json, escribir_atomico, marca, reemplazar, sha256

# Campos que Cowork puede fijar al crear o editar una tarea (E1).
CAMPOS_COWORK = frozenset({"id", "titulo", "prompt", "agente", "agentes_permitidos", "dependencias", "cambio",
                           "rama", "base", "red", "prioridad", "nueva_sesion", "timeout_min", "no_antes_de", "gate"})
# Campos que solo maneja el orquestador.
CAMPOS_INTERNOS = frozenset({"estado", "motivo", "intentos", "max_intentos", "interrupciones", "limites_plan",
                             "resultado", "consumo", "corridas", "creada", "actualizada", "iniciada", "terminada",
                             "historial", "cancelacion", "aviso_interrupcion"})
CAMPOS_GATE_COWORK = frozenset({"requiere", "motivo"})
MAX_PROMPT = 200_000
MAX_TITULO = 200


class ErrorValidacion(ValueError):
    pass


class ErrorRegistro(Exception):
    pass


def _texto(datos: dict, campo: str, maximo: int, obligatorio: bool = True) -> str | None:
    valor = datos.get(campo)
    if valor is None and not obligatorio:
        return None
    if not isinstance(valor, str) or not valor.strip():
        raise ErrorValidacion(f"'{campo}' es obligatorio y debe ser un texto no vacío")
    if len(valor) > maximo:
        raise ErrorValidacion(f"'{campo}' supera {maximo} caracteres")
    return valor


def _booleano(datos: dict, campo: str, defecto: bool) -> bool:
    valor = datos.get(campo, defecto)
    if not isinstance(valor, bool):
        raise ErrorValidacion(f"'{campo}' debe ser true o false")
    return valor


def _entero(datos: dict, campo: str, minimo: int, maximo: int, defecto=None):
    valor = datos.get(campo, defecto)
    if valor is None:
        return None
    if not isinstance(valor, int) or isinstance(valor, bool) or not minimo <= valor <= maximo:
        raise ErrorValidacion(f"'{campo}' debe ser un entero entre {minimo} y {maximo}")
    return valor


def construir_tarea(datos: dict, proyecto, agentes: dict, momento: str) -> dict:
    """Valida los campos que manda Cowork y devuelve la tarea completa con sus valores por defecto (sin estado)."""
    if not isinstance(datos, dict):
        raise ErrorValidacion("cada tarea debe ser un objeto")
    reservados = sorted(set(datos) & CAMPOS_INTERNOS)
    if reservados:
        raise ErrorValidacion(f"campo reservado al orquestador: {', '.join(reservados)}")
    desconocidos = sorted(set(datos) - CAMPOS_COWORK)
    if desconocidos:
        raise ErrorValidacion(f"campo no permitido: {', '.join(desconocidos)}")

    id_tarea = datos.get("id")
    if not isinstance(id_tarea, str) or not ID_OK.match(id_tarea):
        raise ErrorValidacion("id inválido (letras, números, punto, guion y guion bajo)")
    titulo = _texto(datos, "titulo", MAX_TITULO)
    prompt = _texto(datos, "prompt", MAX_PROMPT)

    agente = datos.get("agente")
    if agente not in agentes:
        raise ErrorValidacion(f"agente no configurado: {agente}")
    if not agentes[agente].habilitado:
        raise ErrorValidacion(f"agente no habilitado: {agente}")
    if agente not in proyecto.agentes_permitidos:
        raise ErrorValidacion(f"el proyecto no permite el agente {agente}")
    permitidos = datos.get("agentes_permitidos", [agente])
    if not isinstance(permitidos, list) or not permitidos or not all(isinstance(a, str) for a in permitidos):
        raise ErrorValidacion("agentes_permitidos debe ser una lista de agentes")
    for a in permitidos:
        if a not in agentes or a not in proyecto.agentes_permitidos:
            raise ErrorValidacion(f"agente no permitido en agentes_permitidos: {a}")
    if agente not in permitidos:
        raise ErrorValidacion("agente debe estar en agentes_permitidos")

    dependencias = datos.get("dependencias", [])
    if not isinstance(dependencias, list) or not all(isinstance(d, str) and ID_OK.match(d) for d in dependencias):
        raise ErrorValidacion("dependencias debe ser una lista de ids")
    if id_tarea in dependencias:
        raise ErrorValidacion("una tarea no puede depender de sí misma")
    if len(set(dependencias)) != len(dependencias):
        raise ErrorValidacion("dependencias repetidas")

    cambio = datos.get("cambio")
    if not isinstance(cambio, str) or not NOMBRE_OK.match(cambio):
        raise ErrorValidacion("cambio inválido (minúsculas, números y guiones)")
    rama = datos.get("rama", cambio)
    if not isinstance(rama, str) or not NOMBRE_OK.match(rama):
        raise ErrorValidacion("rama inválida (minúsculas, números y guiones)")
    base = datos.get("base")
    if base is not None and (not isinstance(base, str) or not BASE_OK.match(base)):
        raise ErrorValidacion("base inválida")

    red = _booleano(datos, "red", False)
    if red and not proyecto.red_permitida:
        raise ErrorValidacion("el proyecto no permite tareas con red")
    prioridad = _entero(datos, "prioridad", 0, 1000, defecto=100)
    nueva_sesion = _booleano(datos, "nueva_sesion", False)
    timeout = _entero(datos, "timeout_min", 1, 1440)
    no_antes_de = datos.get("no_antes_de")
    if no_antes_de is not None:
        try:
            if dt.datetime.fromisoformat(str(no_antes_de)).tzinfo is None:
                raise ValueError
        except ValueError:
            raise ErrorValidacion("no_antes_de debe ser una fecha ISO 8601 con zona horaria") from None

    gate_pedido = datos.get("gate", {})
    if not isinstance(gate_pedido, dict) or set(gate_pedido) - CAMPOS_GATE_COWORK:
        raise ErrorValidacion("gate solo admite 'requiere' y 'motivo'")
    requiere = gate_pedido.get("requiere", proyecto.gate_por_defecto)
    if not isinstance(requiere, bool):
        raise ErrorValidacion("gate.requiere debe ser true o false")
    motivo_gate = gate_pedido.get("motivo")
    if motivo_gate is not None and not isinstance(motivo_gate, str):
        raise ErrorValidacion("gate.motivo debe ser un texto")

    return {
        "id": id_tarea, "titulo": titulo, "prompt": prompt, "agente": agente, "agentes_permitidos": list(permitidos),
        "estado": None, "motivo": None, "dependencias": list(dependencias), "cambio": cambio, "rama": rama,
        "base": base, "red": red, "prioridad": prioridad, "nueva_sesion": nueva_sesion, "timeout_min": timeout,
        "no_antes_de": no_antes_de,
        "gate": {"requiere": requiere, "motivo": motivo_gate, "decision": None, "nota": None, "en": None,
                 "huella": None, "via": None},
        "intentos": 0, "max_intentos": 3, "interrupciones": 0, "limites_plan": 0,
        "resultado": None, "consumo": {}, "corridas": [],
        "creada": momento, "actualizada": momento, "iniciada": None, "terminada": None, "historial": [],
    }


def campos_cowork(tarea: dict) -> dict:
    """Los campos de una tarea que Cowork puede editar, en la forma en que los manda."""
    datos = {k: tarea[k] for k in CAMPOS_COWORK if k in tarea and k != "gate"}
    datos = {k: v for k, v in datos.items() if v is not None}
    datos["gate"] = {"requiere": tarea["gate"]["requiere"]}
    if tarea["gate"].get("motivo") is not None:
        datos["gate"]["motivo"] = tarea["gate"]["motivo"]
    return datos


class Registro:
    """Tareas de un proyecto en memoria, con carga robusta y escritura atómica."""

    def __init__(self, ruta: Path):
        self.ruta = Path(ruta)
        self.tareas: dict[str, dict] = {}
        self._huella: str | None = None

    @property
    def ruta_bak(self) -> Path:
        return self.ruta.with_name(self.ruta.name + ".bak")

    @staticmethod
    def _leer(contenido: bytes) -> dict[str, dict]:
        datos = json.loads(contenido.decode("utf-8"))
        if not isinstance(datos, dict) or not isinstance(datos.get("tareas"), list):
            raise ValueError("estructura inválida")
        tareas = {}
        for t in datos["tareas"]:
            if not isinstance(t, dict) or not isinstance(t.get("id"), str):
                raise ValueError("tarea inválida")
            tareas[t["id"]] = t
        return tareas

    def cargar(self) -> list[str]:
        avisos: list[str] = []
        self.tareas, self._huella = {}, None
        if self.ruta.exists():
            contenido = self.ruta.read_bytes()
            try:
                self.tareas = self._leer(contenido)
                self._huella = sha256(contenido)
                return avisos
            except (ValueError, UnicodeDecodeError):
                pass
            danado = self.ruta.with_name(f"{self.ruta.name}.danado-{marca()}")
            if not self.ruta_bak.exists():
                raise ErrorRegistro(f"{self.ruta} está dañado y no hay copia .bak")
            try:
                tareas = self._leer(self.ruta_bak.read_bytes())
            except (ValueError, UnicodeDecodeError) as e:
                raise ErrorRegistro(f"{self.ruta} y su copia .bak están dañados") from e
            reemplazar(self.ruta, danado)
            self.tareas = tareas
            avisos.append(f"registro dañado: se usó {self.ruta_bak.name} y el dañado quedó como {danado.name}")
        elif self.ruta_bak.exists():
            try:
                self.tareas = self._leer(self.ruta_bak.read_bytes())
                avisos.append(f"faltaba {self.ruta.name}: se usó {self.ruta_bak.name}")
            except (ValueError, UnicodeDecodeError) as e:
                raise ErrorRegistro(f"falta {self.ruta} y su copia .bak está dañada") from e
        return avisos

    def revisar_externo(self) -> bool:
        """True si alguien cambió `tareas.json` desde la última lectura o escritura de este registro."""
        if not self.ruta.exists():
            return False
        return self._huella is None or sha256(self.ruta.read_bytes()) != self._huella

    def guardar(self) -> list[str]:
        avisos: list[str] = []
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        contenido = a_json({"v": 1, "tareas": list(self.tareas.values())})
        tmp = self.ruta.with_name(self.ruta.name + ".tmp")
        tmp.write_bytes(contenido)
        if self.ruta.exists():
            actual = self.ruta.read_bytes()
            if self._huella is None or sha256(actual) != self._huella:
                externo = self.ruta.with_name(f"{self.ruta.name}.externo-{marca()}")
                externo.write_bytes(actual)
                avisos.append(f"escritura externa detectada en {self.ruta.name}: se guardó como {externo.name} "
                              "y se mantiene la versión del orquestador")
            escribir_atomico(self.ruta_bak, actual)
        reemplazar(tmp, self.ruta)
        self._huella = sha256(contenido)
        return avisos

    # --- acceso ---

    def obtener(self, id_tarea: str) -> dict | None:
        return self.tareas.get(id_tarea)

    def existe(self, id_tarea: str) -> bool:
        return id_tarea in self.tareas

    def agregar(self, tarea: dict) -> None:
        if tarea["id"] in self.tareas:
            raise ErrorValidacion(f"ya existe una tarea con id {tarea['id']}")
        self.tareas[tarea["id"]] = tarea

    def lista(self) -> list[dict]:
        return list(self.tareas.values())
