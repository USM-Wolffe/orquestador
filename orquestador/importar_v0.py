"""`orq importar-v0` (spec compatibilidad-v0, "Importación del estado v0 sin tocar el origen").

- Lee `sesiones.json` y `trabajos\\pendientes\\*.json` de una carpeta del puente v0. Nunca escribe, mueve ni borra
  nada en esa carpeta.
- Sin `--aplicar` solo muestra lo que importaría.
- Con `--aplicar` toma el candado del orquestador (no corre junto a `orq correr`), guarda las sesiones como
  `(cambio, cc)` en el proyecto y deja cada trabajo, tal como venía, en la entrada de Cowork del proyecto. El bucle
  los convierte y los valida como cualquier trabajo v0; `tareas.json` lo sigue escribiendo solo `orq correr`.
- Las sesiones con repo (`repo:cambio`) se omiten: en el v1 cada repo es un proyecto.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .candado import Candado
from .comun import NOMBRE_OK, escribir_json
from .entrada import SolicitudInvalida, convertir_v0
from .seguridad import sesion_valida
from .sesiones import Sesiones


@dataclass
class PlanImportacion:
    sesiones: list[tuple[str, str]] = field(default_factory=list)  # (cambio, sesión)
    trabajos: list[tuple[str, dict]] = field(default_factory=list)  # (archivo, trabajo v0)
    omitidos: list[str] = field(default_factory=list)


def leer(carpeta: Path) -> PlanImportacion:
    """Arma el plan leyendo la carpeta v0 (solo lectura)."""
    carpeta = Path(carpeta)
    if not carpeta.is_dir():
        raise ValueError(f"no existe la carpeta del v0: {carpeta}")
    plan = PlanImportacion()
    ruta_sesiones = carpeta / "sesiones.json"
    try:
        sesiones = json.loads(ruta_sesiones.read_text(encoding="utf-8")) if ruta_sesiones.exists() else {}
    except (ValueError, UnicodeDecodeError) as e:
        raise ValueError(f"{ruta_sesiones} no es JSON válido: {e}") from e
    if not isinstance(sesiones, dict):
        raise ValueError(f"{ruta_sesiones} debe ser un objeto")
    for clave, sesion in sorted(sesiones.items()):
        if ":" in clave:
            plan.omitidos.append(f"sesión '{clave}': es de otro repo (en el v1 cada repo es un proyecto)")
        elif not NOMBRE_OK.match(clave):
            plan.omitidos.append(f"sesión '{clave}': nombre de cambio inválido")
        elif not sesion_valida(sesion):
            plan.omitidos.append(f"sesión '{clave}': id de sesión inválido")
        else:
            plan.sesiones.append((clave, sesion))
    pendientes = carpeta / "trabajos" / "pendientes"
    for archivo in sorted(pendientes.glob("*.json")) if pendientes.is_dir() else []:
        try:
            trabajo = json.loads(archivo.read_text(encoding="utf-8"))
            if not isinstance(trabajo, dict):
                raise SolicitudInvalida("el trabajo no es un objeto JSON")
            convertir_v0(trabajo)
        except (ValueError, UnicodeDecodeError) as e:
            plan.omitidos.append(f"trabajo {archivo.name}: {e}")
            continue
        plan.trabajos.append((archivo.name, trabajo))
    return plan


def describir(plan: PlanImportacion, proyecto: str, aplicado: bool) -> str:
    verbo = "Importado" if aplicado else "Se importaría"
    lineas = [f"{verbo} en el proyecto '{proyecto}':"]
    lineas += [f"  sesión del cambio {c} → {s}" for c, s in plan.sesiones] or ["  (sin sesiones)"]
    lineas += [f"  trabajo {t.get('id')} (cambio {t.get('cambio')}) desde {a}" for a, t in plan.trabajos] or \
        ["  (sin trabajos pendientes)"]
    lineas += [f"  omitido: {o}" for o in plan.omitidos]
    if not aplicado:
        lineas.append("Simulación: no se escribió nada. Usa --aplicar para importar.")
    return "\n".join(lineas)


def aplicar(config, proyecto, plan: PlanImportacion) -> list[str]:
    """Guarda las sesiones y deja los trabajos en la entrada de Cowork. Devuelve avisos."""
    avisos = []
    candado = Candado(config.raiz / "orquestador.lock")
    candado.tomar()  # CandadoOcupado si `orq correr` está corriendo
    try:
        sesiones = Sesiones(proyecto.carpeta / "sesiones.json")
        for cambio, sesion in plan.sesiones:
            actual = sesiones.obtener(cambio, "cc")
            if actual and actual != sesion:
                avisos.append(f"el cambio {cambio} ya tenía la sesión {actual}; no se reemplazó")
                continue
            sesiones.guardar(cambio, "cc", sesion)
        entrada = proyecto.carpeta_cowork / "entrada"
        entrada.mkdir(parents=True, exist_ok=True)
        for archivo, trabajo in plan.trabajos:
            escribir_json(entrada / f"v0-{Path(archivo).stem}.json", trabajo)
    finally:
        candado.soltar()
    return avisos
