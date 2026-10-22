"""Registro de eventos JSONL append-only por proyecto (spec eventos-actividad).

- Un evento por línea en `proyectos\\<p>\\eventos\\eventos.jsonl`.
- `datos` se copia por lista blanca según el tipo: nunca entran contenido de archivos, diffs ni salidas.
- Los textos pasan por la redacción y por topes de largo, y cada línea mide como máximo 4 KB.
- Cada intento escribe como máximo 2.000 eventos de detalle (mensaje, herramienta, comando).
- La rotación se hace antes de escribir, entre dos líneas, cuando el archivo supera el tope.
- Los lectores ignoran una última línea sin salto.
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import Counter, deque
from pathlib import Path

from .comun import ahora, reemplazar
from .redaccion import MARCA_TRUNCADO, redactar, truncar

VERSION_ESQUEMA = 1
TOPE_LINEA = 4096
TOPE_DETALLE = 2000
DETALLE = frozenset({"mensaje", "herramienta", "comando"})
CAMPOS = {
    "inicio": frozenset({"sesion", "modelo", "retomada", "version", "niveles", "advertencias", "herramientas", "herramientas_omitidas", "mcp"}),
    "mensaje": frozenset({"texto"}),
    "herramienta": frozenset({"nombre", "objetivo", "estado"}),
    "archivo": frozenset({"ruta", "accion"}),
    "comando": frozenset({"comando", "estado", "codigo_salida"}),
    "fin": frozenset({"ok", "duracion_s", "consumo", "eventos_ignorados", "eventos_omitidos"}),
    "error": frozenset({"clase", "mensaje", "reintentar_desde"}),
    "gate": frozenset({"decision", "huella", "via", "sesion"}),
}
CAMPOS_CONSUMO = frozenset({"tokens_entrada", "tokens_salida", "tokens_cache_lectura", "tokens_cache_escritura",
                            "costo_usd", "costo_estimado", "segundos"})
LARGOS = {"texto": 2000, "comando": 1000, "mensaje": 1000, "objetivo": 500, "ruta": 500}
LARGO_POR_DEFECTO = 200
MAX_ADVERTENCIAS = 10


def ruta_para_evento(ruta: Path | str, worktree: Path | str, home: Path | str | None = None) -> str:
    """Ruta relativa al worktree; si queda fuera, con `~` en vez del perfil del usuario."""
    ruta_s = os.path.abspath(os.fspath(ruta))
    for base, prefijo in ((os.path.abspath(os.fspath(worktree)), ""),
                          (os.path.abspath(os.fspath(home or os.environ.get("USERPROFILE") or Path.home())), "~/")):
        b = os.path.normcase(base).rstrip("\\/")
        if os.path.normcase(ruta_s).startswith(b + os.sep):
            return prefijo + Path(ruta_s[len(b) + 1:]).as_posix()
    return Path(ruta_s).as_posix()


def leer_desde(ruta: Path, offset: int = 0) -> tuple[list[dict], int]:
    """Eventos completos desde `offset`. Una última línea sin salto no se consume: se leerá completa después."""
    try:
        with open(ruta, "rb") as f:
            f.seek(offset)
            datos = f.read()
    except FileNotFoundError:
        return [], offset
    fin = datos.rfind(b"\n")
    if fin < 0:
        return [], offset
    eventos = []
    for linea in datos[:fin].split(b"\n"):
        if linea.strip():
            try:
                eventos.append(json.loads(linea))
            except ValueError:
                continue
    return eventos, offset + fin + 1


def _ultimo_seq(ruta: Path) -> int | None:
    try:
        with open(ruta, "rb") as f:
            f.seek(0, os.SEEK_END)
            tam = f.tell()
            f.seek(max(0, tam - 65536))
            datos = f.read()
    except FileNotFoundError:
        return None
    for linea in reversed(datos.split(b"\n")[:-1]):
        try:
            return int(json.loads(linea)["seq"])
        except (ValueError, KeyError, TypeError):
            continue
    return None


class EscritorEventos:
    def __init__(self, carpeta: Path, proyecto: str, tope_bytes: int = 10 * 1024 * 1024, rotados: int = 5,
                 texto_mensajes: str = "truncado", patrones_extra=(), tope_detalle: int = TOPE_DETALLE, reloj=ahora,
                 al_aviso=None):
        self.al_aviso = al_aviso  # callable(texto): avisos técnicos, p. ej. una rotación postergada
        self.carpeta = Path(carpeta)
        self.proyecto = proyecto
        self.tope_bytes = tope_bytes
        self.rotados = rotados
        self.texto_mensajes = texto_mensajes
        self.patrones_extra = tuple(patrones_extra)
        self.tope_detalle = tope_detalle
        self.reloj = reloj
        self.carpeta.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._detalle: Counter = Counter()
        self._omitidos: Counter = Counter()
        self._ignorados: Counter = Counter()
        self._seq = _ultimo_seq(self.archivo)
        if self._seq is None:
            self._seq = _ultimo_seq(self.carpeta / "eventos.1.jsonl") or 0

    @classmethod
    def para_proyecto(cls, config, proyecto, **opciones) -> "EscritorEventos":
        if "al_aviso" not in opciones:
            from .comun import registrar

            opciones["al_aviso"] = lambda texto: registrar(config.raiz, texto)
        return cls(proyecto.carpeta_eventos, proyecto.nombre, tope_bytes=config.eventos_tope_bytes,
                   rotados=config.eventos_rotados, texto_mensajes=proyecto.texto_mensajes,
                   patrones_extra=proyecto.redactar_extra, **opciones)

    @property
    def archivo(self) -> Path:
        return self.carpeta / "eventos.jsonl"

    def ignorado(self, tarea, intento) -> None:
        """Cuenta un evento del agente que el adaptador no conoce (se informa en el `fin` del intento)."""
        with self._lock:
            self._ignorados[(tarea, intento)] += 1

    # --- limpieza de datos ---

    def _texto(self, clave: str, valor: str) -> str:
        return truncar(redactar(valor, self.patrones_extra), LARGOS.get(clave, LARGO_POR_DEFECTO))

    def _limpiar(self, tipo: str, datos: dict) -> dict:
        datos = datos or {}
        if tipo == "mensaje" and self.texto_mensajes == "nunca":
            return {"largo": len(datos.get("texto") or "")}
        limpio = {}
        for clave in CAMPOS[tipo]:
            if clave not in datos:
                continue
            valor = datos[clave]
            if isinstance(valor, str):
                limpio[clave] = self._texto(clave, valor)
            elif valor is None or isinstance(valor, (bool, int, float)):
                limpio[clave] = valor
            elif clave == "consumo" and isinstance(valor, dict):
                limpio[clave] = {k: v for k, v in valor.items()
                                 if k in CAMPOS_CONSUMO and (v is None or isinstance(v, (bool, int, float)))}
            elif clave == "niveles" and isinstance(valor, dict):
                limpio[clave] = {self._texto("nivel", str(k)): self._texto("nivel", str(v)) for k, v in valor.items()}
            elif clave in ("herramientas", "mcp") and isinstance(valor, list):
                limpio[clave] = [self._texto(clave, str(v)) for v in valor[:40]]
            elif clave == "advertencias" and isinstance(valor, list):
                limpio[clave] = [self._texto("advertencia", str(v)) for v in valor[:MAX_ADVERTENCIAS]]
            # cualquier otro tipo de valor se descarta
        return limpio

    @staticmethod
    def _a_linea(evento: dict) -> bytes:
        linea = (json.dumps(evento, ensure_ascii=False) + "\n").encode("utf-8")
        while len(linea) > TOPE_LINEA:
            textos = [(k, v) for k, v in evento["datos"].items() if isinstance(v, str) and len(v) > len(MARCA_TRUNCADO) + 1]
            if not textos:
                listas = [(k, v) for k, v in evento["datos"].items() if isinstance(v, list) and v]
                if not listas:
                    break
                clave, valores = max(listas, key=lambda kv: len(str(kv[1])))
                valores.pop()
                if clave == "herramientas":
                    evento["datos"]["herramientas_omitidas"] = evento["datos"].get("herramientas_omitidas", 0) + 1
                linea = (json.dumps(evento, ensure_ascii=False) + "\n").encode("utf-8")
                continue
            clave, valor = max(textos, key=lambda kv: len(kv[1].encode("utf-8")))
            if len(valor) <= len(MARCA_TRUNCADO) + 1:
                break
            evento["datos"][clave] = truncar(valor, max(len(MARCA_TRUNCADO) + 1, len(valor) // 2))
            linea = (json.dumps(evento, ensure_ascii=False) + "\n").encode("utf-8")
        return linea

    # --- rotación ---

    def _borrar(self, ruta: Path) -> None:
        limite = time.monotonic() + 2.0
        while True:
            try:
                ruta.unlink(missing_ok=True)
                return
            except PermissionError:
                if time.monotonic() >= limite:
                    raise
                time.sleep(0.05)

    def _rotar_si_hace_falta(self) -> None:
        try:
            if self.archivo.stat().st_size <= self.tope_bytes:
                return
        except FileNotFoundError:
            return
        try:
            self._borrar(self.carpeta / f"eventos.{self.rotados}.jsonl")
            for n in range(self.rotados - 1, 0, -1):
                origen = self.carpeta / f"eventos.{n}.jsonl"
                if origen.exists():
                    reemplazar(origen, self.carpeta / f"eventos.{n + 1}.jsonl")
            reemplazar(self.archivo, self.carpeta / "eventos.1.jsonl")
        except PermissionError as e:
            # Un lector tiene el archivo abierto: se reintenta en la próxima escritura y queda en registro.log.
            if self.al_aviso:
                self.al_aviso(f"rotación de eventos postergada en {self.carpeta} ({self.proyecto}): {e}")

    # --- escritura ---

    def escribir(self, tipo: str, datos: dict | None = None, tarea=None, intento=None, agente=None) -> dict | None:
        """Escribe un evento. Devuelve lo que quedó escrito, o None si se omitió por el tope del intento."""
        if tipo not in CAMPOS:
            raise ValueError(f"tipo de evento desconocido: {tipo}")
        with self._lock:
            clave = (tarea, intento)
            if tipo in DETALLE:
                if self._detalle[clave] >= self.tope_detalle:
                    self._omitidos[clave] += 1
                    return None
                self._detalle[clave] += 1
            limpio = self._limpiar(tipo, datos)
            if tipo == "fin":
                if self._ignorados.get(clave):
                    limpio["eventos_ignorados"] = self._ignorados.pop(clave)
                if self._omitidos.get(clave):
                    limpio["eventos_omitidos"] = self._omitidos.pop(clave)
                self._detalle.pop(clave, None)
            self._seq += 1
            evento = {"v": VERSION_ESQUEMA, "ts": self.reloj(), "proyecto": self.proyecto, "tarea": tarea,
                      "intento": intento, "agente": agente, "seq": self._seq, "tipo": tipo, "datos": limpio}
            linea = self._a_linea(evento)
            self._rotar_si_hace_falta()
            with open(self.archivo, "ab") as f:
                f.write(linea)
            return json.loads(linea)


class LectorEventos:
    """Lee `eventos.jsonl` de forma incremental y guarda en memoria los más recientes (tablero y salida de Cowork).

    Solo lee: abre, lee desde el último offset y cierra. Si el archivo rotó (cambió su identidad o es más corto que
    el offset), termina de leer `eventos.1.jsonl` desde el offset anterior y sigue con el archivo nuevo desde 0.
    """

    def __init__(self, carpeta: Path, maximo: int = 20000):
        self.carpeta = Path(carpeta)
        self.recientes: deque[dict] = deque(maxlen=maximo)
        self._offset = 0
        self._identidad = None
        self._ultimo_seq = 0
        self._primera = True
        self._lock = threading.Lock()

    def _agregar(self, eventos: list[dict]) -> None:
        for e in eventos:
            seq = e.get("seq")
            if isinstance(seq, int) and seq > self._ultimo_seq:
                self._ultimo_seq = seq
                self.recientes.append(e)

    def actualizar(self) -> None:
        with self._lock:
            archivo = self.carpeta / "eventos.jsonl"
            rotado = self.carpeta / "eventos.1.jsonl"
            try:
                st = archivo.stat()
            except FileNotFoundError:
                st = None
            if self._primera:
                self._primera = False
                viejos, _ = leer_desde(rotado, 0)
                self._agregar(viejos)
            if st is None:
                return
            identidad = (st.st_dev, st.st_ino)
            if self._identidad is not None and (identidad != self._identidad or st.st_size < self._offset):
                viejos, _ = leer_desde(rotado, self._offset)
                self._agregar(viejos)
                self._offset = 0
            self._identidad = identidad
            nuevos, self._offset = leer_desde(archivo, self._offset)
            self._agregar(nuevos)

    def desde(self, seq: int = 0, tarea: str | None = None) -> list[dict]:
        self.actualizar()
        with self._lock:
            return [e for e in self.recientes if e["seq"] > seq and (tarea is None or e.get("tarea") == tarea)]

    def ultimos(self, n: int) -> list[dict]:
        self.actualizar()
        with self._lock:
            return list(self.recientes)[-n:]
