"""Proyectos de una instalación (spec proyectos y estado-cowork).

Cada proyecto vive en `<raiz>\\proyectos\\<nombre>\\proyecto.json`, con su carpeta de Cowork en
`<cowork_raiz>\\<nombre>\\`. Un proyecto inválido queda inactivo con sus errores y no afecta a los demás.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .comun import BASE_OK, NOMBRE_OK, escribir_json
from .config import Config, ErrorConfig, validar_ubicaciones
from .redaccion import validar_patrones

TEXTO_MENSAJES = ("truncado", "nunca")
CLAVES_PROYECTO = {"nombre", "repo", "base", "carpeta_worktrees", "agentes_permitidos", "limites", "permisos", "red",
                   "gate_por_defecto", "timeout_min", "huellas_aprobadas", "eventos", "facturar_por_api"}

# Comandos que ninguna regla de permiso de un proyecto puede llegar a permitir (spec seguridad-agentes).
COMANDOS_PROHIBIDOS = ("git commit -m x", "git push origin main", "git reset --hard", "git checkout main",
                       "git switch main", "git restore archivo", "git stash", "git merge rama", "git rebase main",
                       "git clean -fd", "git branch -d rama", "git branch -D rama", "git worktree remove wt",
                       "git -C . status")
RUTAS_PROTEGIDAS = (".ssh", ".embudo", ".env", ".claude", ".codex", ".cursor", ".orquestador", "orquestador-cowork")
HERRAMIENTAS_DE_COMANDO = ("bash", "powershell")
HERRAMIENTAS_DE_ARCHIVO = ("read", "edit", "write")

CANDIDATOS = {
    "cc": [r"%USERPROFILE%\.local\bin\claude.exe", r"%APPDATA%\npm\claude.cmd",
           r"%LOCALAPPDATA%\Programs\claude\claude.exe"],
    "git": [r"%ProgramFiles%\Git\cmd\git.exe", r"%ProgramFiles%\Git\mingw64\bin\git.exe",
            r"%LOCALAPPDATA%\Programs\Git\cmd\git.exe"],
}


@dataclass
class Proyecto:
    nombre: str
    carpeta: Path
    carpeta_cowork: Path
    repo: Path | None = None
    base: str = "main"
    carpeta_worktrees: Path | None = None
    agentes_permitidos: list[str] = field(default_factory=list)
    limite_global: int = 1
    limite_por_agente: dict[str, int] = field(default_factory=dict)
    permitir_extra: list[str] = field(default_factory=list)
    denegar_extra: list[str] = field(default_factory=list)
    red_permitida: bool = False
    red_dominios: list[str] = field(default_factory=list)
    gate_por_defecto: bool = True
    timeout_min: int = 90
    huellas_aprobadas: dict[str, str] = field(default_factory=dict)
    texto_mensajes: str = "truncado"
    redactar_extra: list[str] = field(default_factory=list)
    variables_permitidas: list[str] = field(default_factory=list)
    facturar_por_api: bool = False
    errores: list[str] = field(default_factory=list)
    advertencias: list[str] = field(default_factory=list)

    @property
    def activo(self) -> bool:
        return not self.errores

    @property
    def ruta_tareas(self) -> Path:
        return self.carpeta / "tareas.json"

    @property
    def carpeta_decisiones(self) -> Path:
        return self.carpeta / "decisiones"

    @property
    def carpeta_eventos(self) -> Path:
        return self.carpeta / "eventos"

    def worktrees_existentes(self) -> list[Path]:
        if not self.carpeta_worktrees or not self.carpeta_worktrees.is_dir():
            return []
        return [d for d in self.carpeta_worktrees.glob("wt-*") if (d / ".git").exists()]


def _patron_a_regex(patron: str) -> re.Pattern:
    return re.compile("^" + ".*".join(re.escape(p) for p in patron.split("*")) + "$", re.IGNORECASE)


def regla_quita_denegacion(regla: str) -> bool:
    """True si una regla de permiso permitiría algo que las denegaciones obligatorias prohíben."""
    m = re.fullmatch(r"\s*([A-Za-z]+)\s*(?:\((.*)\))?\s*", regla)
    if not m:
        return True  # una regla que no se entiende no se acepta
    herramienta, patron = m.group(1).lower(), m.group(2)
    if herramienta in HERRAMIENTAS_DE_COMANDO:
        if patron is None or patron.strip() in ("", "*"):
            return True
        rx = _patron_a_regex(patron.strip())
        return any(rx.match(c) for c in COMANDOS_PROHIBIDOS)
    if herramienta in HERRAMIENTAS_DE_ARCHIVO:
        if patron is None:
            return False  # el permiso general de la herramienta no quita las denegaciones de rutas (deny gana)
        texto = patron.lower().replace("\\", "/")
        return any(r in texto for r in RUTAS_PROTEGIDAS)
    return False


def _cargar_uno(config: Config, carpeta: Path) -> Proyecto:
    p = Proyecto(nombre=carpeta.name, carpeta=carpeta, carpeta_cowork=config.cowork_raiz / carpeta.name,
                 limite_global=config.limite_global, limite_por_agente=dict(config.limite_por_agente))
    try:
        datos = json.loads((carpeta / "proyecto.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        p.errores.append("falta proyecto.json")
        return p
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        p.errores.append(f"proyecto.json no es JSON válido: {e}")
        return p
    if not isinstance(datos, dict):
        p.errores.append("proyecto.json debe ser un objeto")
        return p

    for clave in sorted(set(datos) - CLAVES_PROYECTO):
        p.advertencias.append(f"clave desconocida en proyecto.json: {clave}")

    nombre = datos.get("nombre")
    if not isinstance(nombre, str) or not NOMBRE_OK.match(nombre):
        p.errores.append("nombre inválido (minúsculas, números y guiones, hasta 61 caracteres)")
    elif nombre != carpeta.name:
        p.errores.append(f"el nombre '{nombre}' no coincide con la carpeta '{carpeta.name}'")

    repo = datos.get("repo")
    if not isinstance(repo, str) or not Path(repo).is_absolute():
        p.errores.append("repo debe ser una ruta absoluta")
    else:
        p.repo = Path(repo)
        if not p.repo.is_dir():
            p.errores.append(f"el repo no existe: {repo}")
        elif not (p.repo / ".git").exists():
            p.errores.append(f"el repo no es un repo git: {repo}")

    base = datos.get("base", "main")
    if not isinstance(base, str) or not BASE_OK.match(base):
        p.errores.append("base inválida")
    else:
        p.base = base

    if datos.get("carpeta_worktrees"):
        wt = Path(str(datos["carpeta_worktrees"]))
        if not wt.is_absolute():
            p.errores.append("carpeta_worktrees debe ser una ruta absoluta")
        p.carpeta_worktrees = wt
    elif p.repo is not None:
        p.carpeta_worktrees = p.repo.parent

    agentes = datos.get("agentes_permitidos")
    if not isinstance(agentes, list) or not agentes or not all(isinstance(a, str) for a in agentes):
        p.errores.append("agentes_permitidos debe ser una lista no vacía")
    else:
        desconocidos = [a for a in agentes if a not in config.agentes]
        if desconocidos:
            p.errores.append(f"agentes no configurados en la instalación: {desconocidos}")
        p.agentes_permitidos = list(agentes)

    limites = datos.get("limites", {}) or {}
    if isinstance(limites, dict):
        g = limites.get("global")
        if g is not None:
            if not isinstance(g, int) or isinstance(g, bool) or g < 1:
                p.errores.append("limites.global debe ser un entero positivo")
            elif g > config.limite_global:
                p.advertencias.append(f"límite global {g} mayor que el de la instalación; se usa {config.limite_global}")
            else:
                p.limite_global = g
        for agente, valor in (limites.get("por_agente", {}) or {}).items():
            tope = config.limite_por_agente.get(agente, 1)
            if not isinstance(valor, int) or isinstance(valor, bool) or valor < 1:
                p.errores.append(f"limites.por_agente.{agente} debe ser un entero positivo")
            elif valor > tope:
                p.advertencias.append(f"límite de {agente} {valor} mayor que el de la instalación; se usa {tope}")
                p.limite_por_agente[agente] = tope
            else:
                p.limite_por_agente[agente] = valor
    else:
        p.errores.append("limites debe ser un objeto")

    permisos = datos.get("permisos", {}) or {}
    if isinstance(permisos, dict):
        permitir = permisos.get("permitir_extra", []) or []
        denegar = permisos.get("denegar_extra", []) or []
        if not all(isinstance(x, str) for x in [*permitir, *denegar]):
            p.errores.append("las reglas de permisos deben ser textos")
        else:
            for regla in permitir:
                if regla_quita_denegacion(regla):
                    p.errores.append(f"'{regla}' quitaría una denegación obligatoria de seguridad")
            p.permitir_extra, p.denegar_extra = list(permitir), list(denegar)
        variables = permisos.get("variables_permitidas", []) or []
        if not isinstance(variables, list) or not all(isinstance(v, str) and v for v in variables):
            p.errores.append("permisos.variables_permitidas debe ser una lista de nombres")
        else:
            p.variables_permitidas = list(variables)
    else:
        p.errores.append("permisos debe ser un objeto")

    red = datos.get("red", {}) or {}
    if isinstance(red, dict):
        p.red_permitida = red.get("permitida", False) is True
        dominios = red.get("dominios", []) or []
        if not all(isinstance(d, str) for d in dominios):
            p.errores.append("red.dominios debe ser una lista de textos")
        else:
            p.red_dominios = list(dominios)
    else:
        p.errores.append("red debe ser un objeto")

    if "gate_por_defecto" in datos:
        if not isinstance(datos["gate_por_defecto"], bool):
            p.errores.append("gate_por_defecto debe ser true o false")
        else:
            p.gate_por_defecto = datos["gate_por_defecto"]

    if "facturar_por_api" in datos:
        if not isinstance(datos["facturar_por_api"], bool):
            p.errores.append("facturar_por_api debe ser true o false")
        else:
            p.facturar_por_api = datos["facturar_por_api"]

    timeout = datos.get("timeout_min", 90)
    if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 1440:
        p.errores.append("timeout_min debe estar entre 1 y 1440")
    else:
        p.timeout_min = timeout

    huellas = datos.get("huellas_aprobadas", {}) or {}
    if not isinstance(huellas, dict) or not all(isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v)
                                                for v in huellas.values()):
        p.errores.append("huellas_aprobadas debe mapear rutas a SHA-256 en hexadecimal")
    else:
        p.huellas_aprobadas = dict(huellas)

    eventos = datos.get("eventos", {}) or {}
    texto = eventos.get("texto_mensajes", "truncado") if isinstance(eventos, dict) else None
    if texto not in TEXTO_MENSAJES:
        p.errores.append("eventos.texto_mensajes debe ser 'truncado' o 'nunca'")
    else:
        p.texto_mensajes = texto
    extra = eventos.get("redactar_extra", []) if isinstance(eventos, dict) else []
    if not isinstance(extra, list) or not all(isinstance(x, str) for x in extra):
        p.errores.append("eventos.redactar_extra debe ser una lista de expresiones regulares")
    else:
        errores = validar_patrones(extra)
        p.errores.extend(errores)
        if not errores:
            p.redactar_extra = list(extra)
    return p


def cargar_proyectos(config: Config) -> list[Proyecto]:
    carpeta = config.carpeta_proyectos
    if not carpeta.is_dir():
        return []
    return [_cargar_uno(config, d) for d in sorted(carpeta.iterdir()) if d.is_dir()]


def sugerir_ejecutables() -> dict[str, list[str]]:
    """Rutas candidatas en ubicaciones conocidas (nunca en el PATH). No escribe la config."""
    return {nombre: [os.path.expandvars(r) for r in rutas if os.path.isfile(os.path.expandvars(r))]
            for nombre, rutas in CANDIDATOS.items()}


def proyecto_nuevo(config: Config, nombre: str, repo: Path, base: str = "main") -> str:
    """Crea `proyectos\\<nombre>\\proyecto.json` con valores seguros y la carpeta de Cowork del proyecto."""
    if not NOMBRE_OK.match(nombre):
        raise ErrorConfig("nombre inválido (minúsculas, números y guiones, hasta 61 caracteres)")
    repo = Path(os.path.abspath(repo))
    if not (repo / ".git").exists():
        raise ErrorConfig(f"{repo} no es un repo git")
    if not BASE_OK.match(base):
        raise ErrorConfig("base inválida")
    carpeta = config.carpeta_proyectos / nombre
    if carpeta.exists():
        raise ErrorConfig(f"el proyecto '{nombre}' ya existe")
    borrador = Proyecto(nombre=nombre, carpeta=carpeta, carpeta_cowork=config.cowork_raiz / nombre, repo=repo,
                        carpeta_worktrees=repo.parent)
    validar_ubicaciones(config, [*cargar_proyectos(config), borrador])
    datos = {"nombre": nombre, "repo": str(repo), "base": base, "carpeta_worktrees": str(repo.parent),
             "agentes_permitidos": ["cc"], "limites": {}, "permisos": {"permitir_extra": [], "denegar_extra": []},
             "red": {"permitida": False, "dominios": []}, "gate_por_defecto": True, "timeout_min": 90,
             "huellas_aprobadas": {}, "eventos": {"texto_mensajes": "truncado"}}
    carpeta.mkdir(parents=True)
    escribir_json(carpeta / "proyecto.json", datos)
    for sub in ("entrada", "respuestas", "salida"):
        (borrador.carpeta_cowork / sub).mkdir(parents=True, exist_ok=True)
    lineas = [f"Proyecto '{nombre}' creado en {carpeta}",
              f"Carpeta para conectar en Cowork: {borrador.carpeta_cowork}"]
    sugerencias = sugerir_ejecutables()
    faltan = [n for n, ruta in (("cc", (config.agentes.get("cc") and config.agentes["cc"].ejecutable)),
                                ("git", config.git)) if not ruta]
    for n in faltan:
        lineas.append(f"Falta la ruta absoluta de {n} en {config.archivo}. Candidatas: "
                      + (", ".join(sugerencias.get(n, [])) or "ninguna encontrada"))
    return "\n".join(lineas)
