"""Salida de solo lectura para Cowork (spec estado-cowork y design D11).

En `<cowork_raiz>\\<proyecto>\\salida\\`:
- `estado.json`: tareas sin el prompt (solo su hash), gate con huella corta, resultado redactado, consumo, las
  últimas 20 entradas del historial, agentes y latido.
- `eventos-recientes.json`: los últimos 300 eventos, con campos de lista blanca y textos de 500 caracteres o menos.
- `consumo.json`: totales por agente y día.
- `resultados\\<id>.md` y `diffstat\\<id>.json`.

La escribe el bucle al final de cada ciclo, de forma atómica. Nunca la lee: para saber si alguien la modificó solo
compara la fecha y el tamaño de lo último que escribió, y si cambiaron la vuelve a escribir.
"""
from __future__ import annotations

import os
from pathlib import Path

from . import vistas
from .comun import a_json, escribir_atomico
from .redaccion import redactar


class SalidaCowork:
    def __init__(self, proyecto):
        self.proyecto = proyecto
        self.carpeta = Path(proyecto.carpeta_cowork) / "salida"
        self._escrito: dict[str, tuple[bytes, tuple[int, int]]] = {}
        self._fuentes: dict[Path, tuple[tuple[int, int], bytes]] = {}

    def _de_fuente(self, origen: Path, transformar) -> bytes | None:
        """Lee un archivo del estado del orquestador y lo transforma, con caché por fecha y tamaño."""
        try:
            st = origen.stat()
        except FileNotFoundError:
            return None
        firma = (st.st_mtime_ns, st.st_size)
        previo = self._fuentes.get(origen)
        if previo and previo[0] == firma:
            return previo[1]
        try:
            contenido = transformar(origen)
        except (OSError, ValueError, UnicodeDecodeError):
            return None
        self._fuentes[origen] = (firma, contenido)
        return contenido

    def _poner(self, relativa: str, contenido: bytes) -> bool:
        destino = self.carpeta / relativa
        previo = self._escrito.get(relativa)
        if previo and previo[0] == contenido:
            try:
                st = destino.stat()
                if (st.st_mtime_ns, st.st_size) == previo[1]:
                    return False
            except FileNotFoundError:
                pass
        destino.parent.mkdir(parents=True, exist_ok=True)
        escribir_atomico(destino, contenido)
        st = destino.stat()
        self._escrito[relativa] = (contenido, (st.st_mtime_ns, st.st_size))
        return True

    def escribir(self, tareas: list[dict], agentes: dict, eventos: list[dict], latido: str) -> int:
        """Escribe lo que cambió. Devuelve cuántos archivos escribió."""
        extra = tuple(self.proyecto.redactar_extra or ())
        archivos = {
            "estado.json": a_json(vistas.estado_cowork(self.proyecto.nombre, tareas, agentes, latido, extra)),
            "eventos-recientes.json": a_json({"eventos": [x for x in (vistas.evento_cowork(e, extra) for e in
                                                                      eventos[-vistas.EVENTOS_COWORK:]) if x]}),
            "consumo.json": a_json({"por_agente_y_dia": vistas.consumo_por_dia(tareas)}),
        }
        perfil = os.environ.get("USERPROFILE")
        for t in tareas:
            informe = self._de_fuente(
                Path(self.proyecto.carpeta) / "resultados" / f"{t['id']}.md",
                lambda r: vistas.ocultar_rutas(redactar(r.read_text(encoding="utf-8"), extra), perfil).encode("utf-8"))
            if informe is not None:
                archivos[f"resultados/{t['id']}.md"] = informe
            diff = self._de_fuente(
                Path(self.proyecto.carpeta) / "diffstat" / f"{t['id']}.json",
                lambda r: a_json(vistas.diffstat_cowork(vistas.leer_diffstat(self.proyecto.carpeta, t["id"]) or {})))
            if diff is not None:
                archivos[f"diffstat/{t['id']}.json"] = diff
        return sum(1 for relativa, contenido in archivos.items() if self._poner(relativa, contenido))
