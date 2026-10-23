"""Orquestador multiagente v1 (E1): punto de entrada.

Uso:
  py -3.12 orq.py [--config RUTA] [--raiz RUTA] <subcomando> ...

Subcomandos:
  correr        bucle del orquestador con el tablero: orq correr [--abrir] [--sin-tablero] [--una-vez]
                [--permitir-codigo-modificado]
  abrir         abre el tablero en el navegador sin token: orq abrir
  tarea         pide reintentar o cancelar una tarea: orq tarea <proyecto> <id> reintentar|cancelar
  proyecto      orq proyecto nuevo <nombre> --repo <ruta> [--base main] | orq proyecto lista
  estado        resumen del estado (solo lee)
  importar-v0   importa el estado del puente v0: orq importar-v0 --desde <carpeta v0> --proyecto <p> [--aplicar]
Solo librería estándar.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from orquestador import VERSION
from orquestador.candado import CandadoOcupado
from orquestador.config import ErrorConfig, cargar_config


def _correr(args) -> int:
    import webbrowser

    from orquestador import acceso, integridad
    from orquestador.candado import CandadoOcupado
    from orquestador.inicio import iniciar
    from orquestador.planificador import Orquestador
    from orquestador.tablero import ErrorTablero, Tablero

    if args.abrir and args.sin_tablero:
        print("error: las opciones --abrir y --sin-tablero no se combinan", file=sys.stderr)
        return 1
    try:
        contexto = iniciar(args.config, args.raiz)
    except CandadoOcupado:
        if args.abrir:
            # Segunda instancia con --abrir: hace lo de `orq abrir` y termina con 1 (design D9).
            acceso.abrir_desde_candado(cargar_config(args.config, args.raiz))
        raise
    tablero = None
    try:
        print(f"Proyectos activos: {', '.join(p.nombre for p in contexto.activos) or 'ninguno'}", flush=True)
        orq = Orquestador(contexto, atar=True, codigo_modificado=integridad.revisar(contexto.config.git),
                          permitir_codigo_modificado=args.permitir_codigo_modificado)
        if not args.sin_tablero:
            tablero = Tablero(orq, contexto.config.puerto)
            try:
                enlace = tablero.iniciar()
            except ErrorTablero as e:
                print(f"error: {e}", file=sys.stderr)
                return 1
            contexto.candado.fijar_puerto(tablero.puerto)
            if args.abrir:
                webbrowser.open(enlace)
            acceso.iniciar_escucha(tablero)
        try:
            orq.correr(una_vez=args.una_vez)
        except KeyboardInterrupt:
            print("Detenido.", flush=True)
        return 0
    finally:
        if tablero:
            tablero.detener()
        contexto.cerrar()


def _abrir(args) -> int:
    from orquestador import acceso

    return acceso.abrir_desde_candado(cargar_config(args.config, args.raiz))


def _estado(args) -> int:
    from orquestador import proyectos, vistas

    config = cargar_config(args.config, args.raiz)
    print(vistas.resumen(config, proyectos.cargar_proyectos(config)))
    return 0


def _importar_v0(args) -> int:
    from orquestador import importar_v0, proyectos

    config = cargar_config(args.config, args.raiz)
    proyecto = next((p for p in proyectos.cargar_proyectos(config) if p.nombre == args.proyecto), None)
    if proyecto is None or not proyecto.activo:
        print(f"error: el proyecto '{args.proyecto}' no existe o está inactivo", file=sys.stderr)
        return 1
    plan = importar_v0.leer(Path(args.desde))
    avisos = importar_v0.aplicar(config, proyecto, plan) if args.aplicar else []
    print(importar_v0.describir(plan, proyecto.nombre, args.aplicar))
    for aviso in avisos:
        print(f"  aviso: {aviso}")
    return 0


def _proyecto(args) -> int:
    from orquestador import proyectos

    config = cargar_config(args.config, args.raiz)
    if args.accion_proyecto == "nuevo":
        print(proyectos.proyecto_nuevo(config, args.nombre, Path(args.repo), args.base))
        return 0
    for p in proyectos.cargar_proyectos(config):
        estado = "activo" if p.activo else "inactivo: " + "; ".join(p.errores)
        print(f"{p.nombre}: {estado}")
    return 0


def _tarea(args) -> int:
    from orquestador import decisiones

    print(decisiones.pedir_desde_cli(cargar_config(args.config, args.raiz), args.proyecto, args.id, args.accion))
    return 0


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="orq", description=f"Orquestador multiagente v1 ({VERSION})")
    parser.add_argument("--config", help="ruta de config.json (por defecto, en la raíz de estado)")
    parser.add_argument("--raiz", help="raíz de estado (por defecto %%USERPROFILE%%\\.orquestador)")
    sub = parser.add_subparsers(dest="subcomando", required=True, metavar="subcomando")

    p_correr = sub.add_parser("correr", help="corre el bucle del orquestador y el tablero")
    p_correr.add_argument("--una-vez", action="store_true", help="procesa un ciclo y termina")
    p_correr.add_argument("--abrir", action="store_true", help="abre el navegador con el enlace inicial")
    p_correr.add_argument("--sin-tablero", action="store_true", help="no levanta el tablero")
    p_correr.add_argument("--permitir-codigo-modificado", action="store_true",
                          help="permite decidir gates aunque el código del orquestador tenga cambios sin commit")
    p_correr.set_defaults(funcion=_correr)

    p_tarea = sub.add_parser("tarea", help="pide reintentar o cancelar una tarea")
    p_tarea.add_argument("proyecto")
    p_tarea.add_argument("id")
    p_tarea.add_argument("accion", choices=["reintentar", "cancelar"])
    p_tarea.set_defaults(funcion=_tarea)

    p_proyecto = sub.add_parser("proyecto", help="crea o lista proyectos")
    sub_proyecto = p_proyecto.add_subparsers(dest="accion_proyecto", required=True, metavar="accion")
    p_nuevo = sub_proyecto.add_parser("nuevo", help="crea un proyecto con valores seguros")
    p_nuevo.add_argument("nombre")
    p_nuevo.add_argument("--repo", required=True, help="ruta del repo git del proyecto")
    p_nuevo.add_argument("--base", default="main", help="rama base (por defecto main)")
    sub_proyecto.add_parser("lista", help="lista los proyectos y su estado")
    p_proyecto.set_defaults(funcion=_proyecto)

    sub.add_parser("estado", help="resumen del estado (solo lee)").set_defaults(funcion=_estado)
    sub.add_parser("abrir", help="abre el tablero en el navegador (sin token)").set_defaults(funcion=_abrir)

    p_importar = sub.add_parser("importar-v0", help="importa sesiones y trabajos del puente v0 (simula por defecto)")
    p_importar.add_argument("--desde", required=True, help="carpeta del puente v0 (no se modifica)")
    p_importar.add_argument("--proyecto", required=True, help="proyecto del v1 que recibe la importación")
    p_importar.add_argument("--aplicar", action="store_true", help="importa de verdad (sin esto, solo muestra)")
    p_importar.set_defaults(funcion=_importar_v0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = construir_parser().parse_args(argv)
    try:
        return args.funcion(args)
    except (ErrorConfig, CandadoOcupado) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
