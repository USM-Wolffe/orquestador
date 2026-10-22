"""Adaptador de Claude Code (`claude -p`), spec adaptadores-agente y seguridad-agentes.

Flags verificados con `claude --help` 2.1.306 y code.claude.com/docs (docs/diseno-orquestador.md, sección 17).
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from ..comun import a_json
from ..eventos import ruta_para_evento
from .base import (IGNORADO, ContextoLanzamiento, EstadoLectura, Lanzamiento, Limite, Resultado)

HERRAMIENTAS_BASE = ("Read", "Edit", "Write", "Glob", "Grep", "Bash", "TodoWrite", "Skill")
HERRAMIENTAS_RED = ("WebFetch", "WebSearch")
COMANDOS = frozenset({"Bash", "PowerShell"})
EDICION = {"Edit": "editar", "MultiEdit": "editar", "NotebookEdit": "editar", "Write": "escribir"}
CONSULTA = {"Read": "leer", "NotebookRead": "leer", "Glob": "buscar", "Grep": "buscar", "WebFetch": "web",
            "WebSearch": "web", "TodoWrite": "tareas", "Skill": "skill"}

# Git de solo lectura y herramientas del proyecto, como en la lista `permitir` del v0.
PERMITIR_BASE = (
    "Read", "Edit", "Write", "Glob", "Grep", "TodoWrite", "Skill",
    "Bash(py *)", "Bash(python *)", "Bash(.venv/Scripts/python *)", "Bash(pytest *)", "Bash(openspec *)",
    "Bash(git status)", "Bash(git status *)", "Bash(git diff)", "Bash(git diff *)", "Bash(git log)",
    "Bash(git log *)", "Bash(git show *)", "Bash(git branch)", "Bash(git branch --show-current)",
    "Bash(git rev-parse *)", "Bash(git ls-files *)", "Bash(git grep *)",
    "Bash(ls)", "Bash(ls *)", "Bash(cat *)", "Bash(head *)", "Bash(tail *)", "Bash(wc *)", "Bash(grep *)",
    "Bash(find *)", "Bash(mkdir *)", "Bash(pwd)", "Bash(echo *)", "Bash(sort *)", "Bash(diff *)",
    "Bash(which *)", "Bash(test *)",
)
GIT_PROHIBIDO = ("commit", "push", "reset", "checkout", "switch", "restore", "stash", "merge", "rebase", "clean",
                 "branch -d", "branch -D", "worktree remove", "-C")
RED_PROHIBIDA = ("curl", "wget", "Invoke-WebRequest", "Invoke-RestMethod", "iwr", "irm", "pip install",
                 "npm install")
RUTAS_HOME_PROHIBIDAS = ("~/.ssh/**", "~/.embudo/**", "~/.claude/**", "~/.codex/**", "~/.cursor/**")
RUTAS_GLOBALES_PROHIBIDAS = ("//**/.env", "//**/.env.*")

LIMITE_TEXTO = re.compile(r"(?i)(hit your (?:\w+ )?limit|usage limit|session limit|limit · resets|rate limit)")
REINICIO_TEXTO = re.compile(r"(?i)resets\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?")
SESION_INEXISTENTE = re.compile(r"(?i)no conversation found with session id")


def regla_ruta(ruta: Path) -> str:
    """`C:\\Users\\x\\.orquestador` → `//c/Users/x/.orquestador/**` (forma de las reglas de Claude Code)."""
    absoluta = Path(ruta).absolute()
    unidad = absoluta.drive.rstrip(":").lower()
    resto = absoluta.as_posix()[len(absoluta.drive):].rstrip("/")
    return f"//{unidad}{resto}/**" if unidad else f"/{resto}/**"


def denegaciones(config, proyecto, red: bool) -> list[str]:
    reglas = []
    for herramienta in ("Bash", "PowerShell"):
        for cmd in GIT_PROHIBIDO:
            reglas += [f"{herramienta}(git {cmd})", f"{herramienta}(git {cmd} *)"]
        if not red:
            for cmd in RED_PROHIBIDA:
                reglas += [f"{herramienta}({cmd})", f"{herramienta}({cmd} *)"]
    rutas = [*RUTAS_HOME_PROHIBIDAS, *RUTAS_GLOBALES_PROHIBIDAS, regla_ruta(config.raiz), regla_ruta(config.cowork_raiz)]
    for herramienta in ("Read", "Edit"):
        reglas += [f"{herramienta}({r})" for r in rutas]
    return reglas + list(proyecto.denegar_extra)


def herramientas(red: bool) -> list[str]:
    return [*HERRAMIENTAS_BASE, *(HERRAMIENTAS_RED if red else ())]


def perfil(config, proyecto, red: bool) -> dict:
    permitir = list(PERMITIR_BASE) + list(proyecto.permitir_extra)
    if red:
        permitir += [f"WebFetch(domain:{d})" for d in proyecto.red_dominios] or ["WebFetch"]
        permitir.append("WebSearch")
    return {"permissions": {"defaultMode": "dontAsk", "allow": permitir, "deny": denegaciones(config, proyecto, red),
                            "disableBypassPermissionsMode": "disable"},
            "disableAllHooks": True}


def _hora_desde_texto(texto: str, ahora: dt.datetime) -> str | None:
    m = REINICIO_TEXTO.search(texto or "")
    if not m:
        return None
    hora, minuto, ampm = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
    if ampm == "pm" and hora < 12:
        hora += 12
    if ampm == "am" and hora == 12:
        hora = 0
    if not (0 <= hora <= 23 and 0 <= minuto <= 59):
        return None
    candidato = ahora.replace(hour=hora, minute=minuto, second=0, microsecond=0)
    if candidato <= ahora:
        candidato += dt.timedelta(days=1)
    return candidato.isoformat(timespec="seconds")


def _desde_epoch(valor) -> str | None:
    if not isinstance(valor, (int, float)) or isinstance(valor, bool) or valor <= 0:
        return None
    segundos = valor / 1000 if valor > 1e12 else valor
    return dt.datetime.fromtimestamp(segundos).astimezone().isoformat(timespec="seconds")


class AdaptadorCC:
    nombre = "cc"
    version_minima = "2.1.302"
    version_verificada = "2.1.306"
    banderas_prohibidas = ("--dangerously-skip-permissions", "--allow-dangerously-skip-permissions")
    valores_prohibidos = {"--permission-mode": ("bypassPermissions", "auto")}

    def __init__(self, agente, reloj=None):
        self.agente = agente
        self.reloj = reloj or (lambda: dt.datetime.now().astimezone())

    # --- lanzamiento ---

    def lanzamiento(self, ctx: ContextoLanzamiento) -> Lanzamiento:
        red = bool(ctx.tarea.get("red"))
        ruta_perfil = ctx.carpeta_corrida / "perfil-cc.json"
        argv = [*self.agente.ejecutable, "-p", "--output-format", "stream-json", "--verbose",
                "--permission-mode", "dontAsk", "--permission-prompts", "none"]
        argv += ["--restricted"] if self.agente.restricted else ["--setting-sources", "user"]
        argv += ["--tools", ",".join(herramientas(red)), "--settings", str(ruta_perfil), "--strict-mcp-config"]
        argv += ["--resume", ctx.sesion] if ctx.retomar else ["--session-id", ctx.sesion]
        env = dict(ctx.entorno)
        env.pop("CLAUDE_CODE_EFFORT_LEVEL", None)  # tiene precedencia sobre --effort (doc model-config)
        env["CLAUDE_CODE_SUBPROCESS_ENV_SCRUB"] = "1"
        env["DISABLE_AUTOUPDATER"] = "1"
        return Lanzamiento(argv=argv, env=env, cwd=ctx.worktree, stdin=ctx.prompt,
                           archivos={ruta_perfil: a_json(perfil(ctx.config, ctx.proyecto, red))})

    # --- lectura ---

    def _objetivo(self, nombre: str, entrada: dict, estado: EstadoLectura):
        for clave in ("file_path", "notebook_path", "path"):
            if isinstance(entrada.get(clave), str):
                return ruta_para_evento(entrada[clave], estado.worktree)
        for clave in ("pattern", "url", "query", "skill", "command"):
            if isinstance(entrada.get(clave), str):
                return entrada[clave]
        return None

    def _consulta(self, nombre: str) -> str:
        if nombre.startswith("mcp__"):
            return "mcp:" + nombre[5:].replace("__", ":")
        return CONSULTA.get(nombre, f"otra:{nombre}")

    def normalizar(self, linea: dict, estado: EstadoLectura) -> list[tuple[str, dict]]:
        tipo, subtipo = linea.get("type"), linea.get("subtype")
        if tipo == "system":
            if subtipo == "init":
                estado.sesion = linea.get("session_id") or estado.sesion
                estado.modelo = linea.get("model")
                return [("inicio", {"sesion": estado.sesion, "modelo": estado.modelo, "retomada": estado.retomada})]
            return []  # api_retry, hooks, etc.: conocidos, sin evento propio
        if tipo == "assistant":
            if linea.get("error") == "rate_limit":
                estado.limite_visto = True
            salida = []
            for bloque in (linea.get("message") or {}).get("content") or []:
                if bloque.get("type") == "text" and bloque.get("text"):
                    salida.append(("mensaje", {"texto": bloque["text"]}))
                elif bloque.get("type") == "tool_use":
                    nombre, entrada = bloque.get("name", ""), bloque.get("input") or {}
                    estado.pendientes[bloque.get("id")] = (nombre, entrada)
                    if nombre in COMANDOS:
                        salida.append(("comando", {"comando": str(entrada.get("command", "")), "estado": "en_curso"}))
            return salida
        if tipo == "user":
            salida = []
            for bloque in (linea.get("message") or {}).get("content") or []:
                if not isinstance(bloque, dict) or bloque.get("type") != "tool_result":
                    continue
                nombre, entrada = estado.pendientes.pop(bloque.get("tool_use_id"), ("", {}))
                error = bool(bloque.get("is_error"))
                if nombre in COMANDOS:
                    salida.append(("comando", {"comando": str(entrada.get("command", "")),
                                               "estado": "error" if error else "ok", "codigo_salida": None}))
                elif nombre in EDICION and not error:
                    salida.append(("archivo", {"ruta": self._objetivo(nombre, entrada, estado),
                                               "accion": EDICION[nombre]}))
                elif nombre:
                    salida.append(("herramienta", {"nombre": EDICION.get(nombre) or self._consulta(nombre),
                                                   "objetivo": self._objetivo(nombre, entrada, estado),
                                                   "estado": "error" if error else "ok"}))
            return salida
        if tipo == "rate_limit_event":
            info = linea.get("rate_limit_info") or {}
            if info.get("status") == "rejected":
                estado.limite_visto = True
                estado.limite_hasta = _desde_epoch(info.get("resetsAt")) or estado.limite_hasta
            return []
        if tipo == "result":
            estado.resultado = linea
            estado.sesion = linea.get("session_id") or estado.sesion
            salida = []
            for negada in linea.get("permission_denials") or []:
                nombre, entrada = negada.get("tool_name", ""), negada.get("tool_input") or {}
                if nombre in COMANDOS:
                    salida.append(("comando", {"comando": str(entrada.get("command", "")), "estado": "negado",
                                               "codigo_salida": None}))
                else:
                    salida.append(("herramienta", {"nombre": EDICION.get(nombre) or self._consulta(nombre),
                                                   "objetivo": self._objetivo(nombre, entrada, estado),
                                                   "estado": "negado"}))
            return salida
        return [(IGNORADO, {})]

    # --- cierre ---

    def cierre(self, estado: EstadoLectura, codigo: int | None, stderr: str, duracion_s: float) -> Resultado:
        r = estado.resultado or {}
        textos = [r.get("result") or "", *[str(e) for e in r.get("errors") or []]]
        texto = "\n".join(t for t in textos if t)
        todo = f"{texto}\n{stderr or ''}"
        uso = r.get("usage") or {}
        consumo = {"tokens_entrada": uso.get("input_tokens"), "tokens_salida": uso.get("output_tokens"),
                   "tokens_cache_lectura": uso.get("cache_read_input_tokens"),
                   "tokens_cache_escritura": uso.get("cache_creation_input_tokens"),
                   "costo_usd": r.get("total_cost_usd"),
                   "costo_estimado": r.get("total_cost_usd") is not None, "segundos": round(duracion_s, 1)}
        resultado = Resultado(ok=bool(r) and not r.get("is_error") and codigo == 0, texto=texto, codigo_salida=codigo,
                              duracion_s=duracion_s, sesion=estado.sesion, modelo=estado.modelo, consumo=consumo,
                              negaciones=list(r.get("permission_denials") or []))
        if SESION_INEXISTENTE.search(todo):
            resultado.sesion_inexistente = True
        if estado.limite_visto or (not resultado.ok and LIMITE_TEXTO.search(todo)):
            hasta = estado.limite_hasta or _hora_desde_texto(todo, self.reloj())
            resultado.limite = Limite(hasta=hasta, texto=(texto or stderr or "")[:500])
            resultado.ok = False
            resultado.error = {"clase": "limite_uso", "mensaje": resultado.limite.texto}
        elif not resultado.ok:
            if not r:
                mensaje = stderr.strip()[-1000:] or f"el agente terminó con código {codigo} sin evento de resultado"
            else:
                mensaje = texto or f"el agente terminó con código {codigo}"
            resultado.error = {"clase": "agente", "mensaje": mensaje}
        return resultado


def leer_perfil(ruta: Path) -> dict:
    return json.loads(Path(ruta).read_text(encoding="utf-8"))
