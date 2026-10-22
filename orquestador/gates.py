"""Gate por botón (spec aprobacion-gates y design D5).

- El tablero valida sesión, CSRF, origen y formato, y llama a `preparar` o `confirmar`.
- Las dos llamadas viajan al bucle de `orq correr` por una cola en memoria: el bucle revisa el estado de la tarea y
  recalcula la huella con git (el tablero nunca corre git ni escribe archivos).
- `preparar` termina con un código de 6 dígitos que solo se imprime en la terminal: un solo uso, 120 s y ligado a
  la tarea, la decisión y la huella. En memoria se guarda solo su SHA-256.
- Tres confirmaciones con código erróneo bloquean los gates hasta reiniciar.
- Si el código del orquestador tiene cambios sin commit (o no se pudo verificar), los gates quedan deshabilitados
  salvo `--permitir-codigo-modificado`.
"""
from __future__ import annotations

import hashlib
import hmac
import queue
import re
import secrets
import threading
import time
from dataclasses import dataclass, field

VIGENCIA_CODIGO_S = 120.0
MAX_ERRORES = 3
ESPERA_BUCLE_S = 20.0
MAX_NOTA = 2000
HUELLA_OK = re.compile(r"^[0-9a-f]{64}$")


def _hash(codigo: str) -> str:
    return hashlib.sha256(codigo.encode("utf-8")).hexdigest()


@dataclass
class Peticion:
    paso: str  # preparar | confirmar
    proyecto: str
    id: str
    decision: str
    huella: str
    nota: str | None
    sesion: str  # identificador corto de la sesión del tablero (nunca la sesión completa)
    listo: threading.Event = field(default_factory=threading.Event)
    respuesta: tuple[int, dict] | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _estado: str = "nueva"  # nueva | tomada | abandonada

    def tomar(self) -> bool:
        """El bucle la toma; falla si el tablero ya dejó de esperarla."""
        with self._lock:
            if self._estado != "nueva":
                return False
            self._estado = "tomada"
            return True

    def abandonar(self) -> bool:
        with self._lock:
            if self._estado != "nueva":
                return False
            self._estado = "abandonada"
            return True

    def responder(self, estado: int, cuerpo: dict) -> None:
        self.respuesta = (estado, cuerpo)
        self.listo.set()


class Gates:
    def __init__(self, terminal=print, reloj=time.monotonic, codigo_modificado: list[str] | None = None,
                 permitir_modificado: bool = False):
        self.terminal = terminal
        self.reloj = reloj
        self.codigo_modificado = codigo_modificado  # None: no se verificó
        self.permitir_modificado = permitir_modificado
        self.cola: queue.Queue[Peticion] = queue.Queue()
        self.avisos: queue.Queue[tuple[str, str, str]] = queue.Queue()  # (proyecto, tarea, texto) para el bucle
        self.errores = 0
        self.bloqueados = False
        self._codigos: dict[tuple[str, str], dict] = {}
        self._lock = threading.Lock()

    # --- estado ---

    @property
    def aviso_integridad(self) -> str | None:
        if self.codigo_modificado is None:
            return "no se verificó la integridad del código del orquestador"
        if self.codigo_modificado:
            return "el código del orquestador tiene cambios sin commit: " + ", ".join(self.codigo_modificado[:10])
        return None

    @property
    def motivo_deshabilitados(self) -> str | None:
        if self.bloqueados:
            return "gates bloqueados hasta reiniciar"
        if self.aviso_integridad and not self.permitir_modificado:
            return "gates deshabilitados: " + self.aviso_integridad
        return None

    # --- llamadas del tablero ---

    @staticmethod
    def _validar(decision, huella, nota) -> str | None:
        if decision not in ("aprobar", "rechazar"):
            return "decisión inválida (aprobar o rechazar)"
        if not isinstance(huella, str) or not HUELLA_OK.match(huella):
            return "falta la huella del estado revisado"
        if nota is not None and (not isinstance(nota, str) or len(nota) > MAX_NOTA):
            return f"la nota debe ser un texto de hasta {MAX_NOTA} caracteres"
        if decision == "rechazar" and not (nota or "").strip():
            return "rechazar exige una nota"
        return None

    def preparar(self, proyecto: str, id_tarea: str, decision, huella, nota, sesion: str) -> tuple[int, dict]:
        motivo = self.motivo_deshabilitados
        if motivo:
            return 423, {"error": motivo}
        error = self._validar(decision, huella, nota)
        if error:
            return 400, {"error": error}
        return self._al_bucle(Peticion("preparar", proyecto, id_tarea, decision, huella, nota, sesion))

    def confirmar(self, proyecto: str, id_tarea: str, decision, huella, nota, codigo, sesion: str) -> tuple[int, dict]:
        motivo = self.motivo_deshabilitados
        if motivo:
            return 423, {"error": motivo}
        error = self._validar(decision, huella, nota)
        if error:
            return 400, {"error": error}
        bloqueo = None
        with self._lock:
            vigente = self._codigos.get((proyecto, id_tarea))
            vencido = vigente is not None and (vigente["usado"] or self.reloj() > vigente["vence"])
            correcto = (vigente is not None and not vencido and vigente["decision"] == decision
                        and vigente["huella"] == huella and isinstance(codigo, str)
                        and hmac.compare_digest(vigente["hash"], _hash(codigo.strip())))
            if correcto:
                vigente["usado"] = True
            else:
                self.errores += 1
                if self.errores >= MAX_ERRORES and not self.bloqueados:
                    self.bloqueados = True
                    bloqueo = f"{self.errores} confirmaciones de gate con código erróneo: gates bloqueados hasta reiniciar"
        if bloqueo:
            self.terminal(f"[gate] {bloqueo}")
            self.avisos.put((proyecto, id_tarea, bloqueo))
        if not correcto:
            return 403, {"error": "código vencido o ya usado" if vencido else "código incorrecto"}
        return self._al_bucle(Peticion("confirmar", proyecto, id_tarea, decision, huella, nota, sesion))

    def _al_bucle(self, peticion: Peticion) -> tuple[int, dict]:
        self.cola.put(peticion)
        if not peticion.listo.wait(ESPERA_BUCLE_S):
            if peticion.abandonar():
                return 503, {"error": "el orquestador no respondió a tiempo; vuelve a intentar"}
            peticion.listo.wait(60)  # el bucle ya la tomó: se espera su respuesta
        return peticion.respuesta or (503, {"error": "el orquestador no respondió"})

    # --- llamadas del bucle ---

    def peticiones(self) -> list[Peticion]:
        tomadas = []
        while True:
            try:
                p = self.cola.get_nowait()
            except queue.Empty:
                return tomadas
            if p.tomar():
                tomadas.append(p)

    def avisos_pendientes(self) -> list[tuple[str, str, str]]:
        salida = []
        while True:
            try:
                salida.append(self.avisos.get_nowait())
            except queue.Empty:
                return salida

    def emitir_codigo(self, peticion: Peticion) -> None:
        """Genera el código y lo imprime solo en la terminal; en memoria queda su SHA-256."""
        codigo = f"{secrets.randbelow(10 ** 6):06d}"
        with self._lock:
            self._codigos[(peticion.proyecto, peticion.id)] = {
                "hash": _hash(codigo), "decision": peticion.decision, "huella": peticion.huella,
                "vence": self.reloj() + VIGENCIA_CODIGO_S, "usado": False}
        accion = "aprobar" if peticion.decision == "aprobar" else "rechazar"
        self.terminal(f"[gate] Código para {accion} {peticion.proyecto}/{peticion.id} "
                      f"(huella {peticion.huella[:12]}): {codigo} · vence en {int(VIGENCIA_CODIGO_S)} s")
