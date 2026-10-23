"""`orq instalar` (design D10 y D11, spec instalacion).

Simula por defecto un plan de pasos; solo con `--aplicar` escribe, y nunca pisa un `config.json` ni un `.cmd`
ajenos. Detecta herramientas solo en rutas conocidas (nunca el PATH), revisa sesiones solo por código de salida
(sin leer credenciales ni la salida) y avisa si el remoto de origin sigue con push habilitado.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import acceso, seguridad
from .adaptadores.base import version_de
from .integridad import INSTALACION
from .procesos import CREATE_NO_WINDOW

TIMEOUT_S = 10.0
EJEMPLO_CONFIG = Path(__file__).resolve().parent.parent / "ejemplos" / "config.example.json"
PUSH_ANULADO = "no-push"


@dataclass
class Paso:
    nombre: str
    estado: str  # "ya estaba" | "crearía" | "creado" | "falta" | "revisar"
    detalle: str
    pendiente: str | None = None


@dataclass
class Hallazgo:
    herramienta: str
    ruta: str | None
    version: str | None = None
    sesion: str | None = None  # "ok", "sin sesión", "se verifica en E4", None
    detalle: str = ""


@dataclass
class Plan:
    pasos: list[Paso] = field(default_factory=list)
    hallazgos: list[Hallazgo] = field(default_factory=list)
    pendientes: list[str] = field(default_factory=list)
    push_anulado: bool | None = None  # True / False / None si no se pudo revisar


def _bases(entorno: dict[str, str] | None = None) -> dict[str, Path]:
    env = entorno if entorno is not None else os.environ
    home = Path(env.get("USERPROFILE") or Path.home())
    return {
        "USERPROFILE": home,
        "LOCALAPPDATA": Path(env.get("LOCALAPPDATA") or home / "AppData" / "Local"),
        "APPDATA": Path(env.get("APPDATA") or home / "AppData" / "Roaming"),
        "ProgramFiles": Path(env.get("ProgramFiles") or r"C:\Program Files"),
    }


def _argv(ruta: Path, *args: str) -> list[str]:
    """Arma el argv: los `.cmd` van por System32\\cmd.exe (ruta absoluta, sin PATH)."""
    if ruta.suffix.lower() == ".cmd":
        comspec = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "cmd.exe")
        return [comspec, "/c", str(ruta), *args]
    return [str(ruta), *args]


def _ejecutar_default(comando: list[str], *, leer_salida: bool, entorno: dict[str, str],
                      timeout_s: float = TIMEOUT_S) -> tuple[int, str]:
    """Corre un comando: con leer_salida=False, stdout/stderr van a DEVNULL (sesiones); si no, captura versión."""
    kwargs = {"stdin": subprocess.DEVNULL, "env": entorno, "timeout": timeout_s,
              "creationflags": CREATE_NO_WINDOW}
    try:
        if leer_salida:
            r = subprocess.run(comando, capture_output=True, text=True, encoding="utf-8", errors="replace",
                               **kwargs)
            return r.returncode, (r.stdout or "") + (r.stderr or "")
        r = subprocess.run(comando, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
        return r.returncode, ""
    except (OSError, subprocess.TimeoutExpired):
        return -1, ""  # no responde o no se puede ejecutar: se informa como sin versión o sin sesión


def _version_texto(salida: str) -> str | None:
    v = version_de(salida)
    return ".".join(map(str, v)) if v else None


def _candidatos_git(bases: dict[str, Path]) -> list[Path]:
    return [bases["ProgramFiles"] / "Git" / "cmd" / "git.exe",
            bases["LOCALAPPDATA"] / "Programs" / "Git" / "cmd" / "git.exe"]


def _candidatos_claude(bases: dict[str, Path]) -> list[Path]:
    return [bases["USERPROFILE"] / ".local" / "bin" / "claude.exe",
            bases["APPDATA"] / "npm" / "claude.cmd"]


def _candidatos_codex(bases: dict[str, Path]) -> list[Path]:
    raiz = bases["LOCALAPPDATA"] / "OpenAI" / "Codex" / "bin"
    if not raiz.is_dir():
        return []
    return sorted(raiz.glob("*/codex.exe"))


def _candidato_cursor(bases: dict[str, Path]) -> Path:
    return bases["LOCALAPPDATA"] / "cursor-agent" / "agent.ps1"


def detectar(bases: dict[str, Path] | None = None, ejecutar=None, entorno_base=None) -> list[Hallazgo]:
    """Busca herramientas en rutas conocidas. Nunca consulta el PATH ni abre archivos de credenciales."""
    bases = bases or _bases()
    ejecutar = ejecutar or _ejecutar_default
    entorno = seguridad.entorno_filtrado(entorno_base if entorno_base is not None else os.environ)
    hallazgos: list[Hallazgo] = []

    # Python: el que corre instalar (≥ 3.12) y py.exe (informativo)
    py_ok = sys.version_info >= (3, 12)
    hallazgos.append(Hallazgo(
        "python", sys.executable if py_ok else None,
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        detalle="" if py_ok else "se necesita Python 3.12 o superior"))
    py_launcher = bases["LOCALAPPDATA"] / "Programs" / "Python" / "Launcher" / "py.exe"
    if not py_launcher.is_file():
        py_launcher = bases["ProgramFiles"] / "Python312" / "py.exe"  # informativo si existe
    if py_launcher.is_file():
        hallazgos.append(Hallazgo("py", str(py_launcher), detalle="lanzador (informativo)"))

    # git
    git_ruta = next((p for p in _candidatos_git(bases) if p.is_file()), None)
    if git_ruta is None:
        hallazgos.append(Hallazgo("git", None, detalle=f"faltante; se esperaba {_candidatos_git(bases)[0]}"))
    else:
        codigo, salida = ejecutar(_argv(git_ruta, "--version"), leer_salida=True, entorno=entorno)
        ver = _version_texto(salida) if codigo == 0 else None
        hallazgos.append(Hallazgo("git", str(git_ruta), ver,
                                  detalle="" if ver else "no responde a --version"))

    # claude
    claude_ruta = next((p for p in _candidatos_claude(bases) if p.is_file()), None)
    if claude_ruta is None:
        hallazgos.append(Hallazgo("claude", None, detalle="faltante"))
    else:
        codigo, salida = ejecutar(_argv(claude_ruta, "--version"), leer_salida=True, entorno=entorno)
        ver = _version_texto(salida) if codigo == 0 else None
        sesion = None
        if ver:
            codigo_auth, _ = ejecutar(_argv(claude_ruta, "auth", "status"), leer_salida=False, entorno=entorno)
            sesion = "ok" if codigo_auth == 0 else "sin sesión"
        hallazgos.append(Hallazgo("claude", str(claude_ruta), ver, sesion,
                                  detalle="" if ver else "no responde a --version"))

    # codex: versión más alta; en empate, carpeta más reciente
    codex_cands = [p for p in _candidatos_codex(bases) if p.is_file()]
    mejor: tuple[tuple[int, int, int], float, Path, str] | None = None
    for ruta in codex_cands:
        codigo, salida = ejecutar(_argv(ruta, "--version"), leer_salida=True, entorno=entorno)
        ver_t = version_de(salida) if codigo == 0 else None
        if ver_t is None:
            continue
        mtime = ruta.parent.stat().st_mtime
        candidato = (ver_t, mtime, ruta, ".".join(map(str, ver_t)))
        if mejor is None or candidato[0] > mejor[0] or (candidato[0] == mejor[0] and candidato[1] > mejor[1]):
            mejor = candidato
    if mejor is None:
        hallazgos.append(Hallazgo("codex", None, detalle="faltante (opcional, para E2)"))
    else:
        _, _, ruta, ver = mejor
        codigo_login, _ = ejecutar(_argv(ruta, "login", "status"), leer_salida=False, entorno=entorno)
        sesion = "ok" if codigo_login == 0 else "sin sesión"
        hallazgos.append(Hallazgo("codex", str(ruta), ver, sesion))

    # Cursor: solo existencia (el .ps1 no se ejecuta)
    cursor = _candidato_cursor(bases)
    if cursor.is_file():
        hallazgos.append(Hallazgo("cursor", str(cursor), sesion="se verifica en E4",
                                  detalle="encontrado; se verifica en E4"))
    else:
        hallazgos.append(Hallazgo("cursor", None, detalle="faltante (opcional, para E4)"))

    return hallazgos


def pushurl_del_remoto(git: str | None, repo: Path = INSTALACION) -> str | None:
    """Lee `remote.origin.pushurl` en modo lectura. None si no está o no se pudo consultar."""
    if not git or not Path(git).is_file():
        return None
    entorno = {**seguridad.entorno_filtrado(os.environ), "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"}
    try:
        r = subprocess.run([git, "config", "--get", "remote.origin.pushurl"], cwd=str(repo),
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           stdin=subprocess.DEVNULL, env=entorno, creationflags=CREATE_NO_WINDOW, timeout=TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    return (r.stdout or "").strip() or None


def hay_origin(git: str | None, repo: Path = INSTALACION) -> bool | None:
    """True/False si el repo tiene o no un remoto `origin`; None si no se pudo revisar (se trata como que sí).

    Usa `git remote`, que solo lista nombres: no lee URL que podrían traer un token.
    """
    if not git or not Path(git).is_file():
        return None
    entorno = {**seguridad.entorno_filtrado(os.environ), "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"}
    try:
        r = subprocess.run([git, "remote"], cwd=str(repo), capture_output=True, text=True, encoding="utf-8",
                           errors="replace", stdin=subprocess.DEVNULL, env=entorno, creationflags=CREATE_NO_WINDOW,
                           timeout=TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    return "origin" in (r.stdout or "").split()


def aviso_push(git: str | None, repo: Path = INSTALACION) -> str | None:
    """Texto de aviso si el push por defecto sigue habilitado; None si está anulado o no se pudo revisar."""
    if not git or not Path(git).is_file():
        return None
    entorno = {**seguridad.entorno_filtrado(os.environ), "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"}
    try:
        r = subprocess.run([git, "rev-parse", "--is-inside-work-tree"], cwd=str(repo),
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           stdin=subprocess.DEVNULL, env=entorno, creationflags=CREATE_NO_WINDOW,
                           timeout=TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0 or hay_origin(git, repo) is False:
        return None  # sin remoto origin no hay push que anular
    valor = pushurl_del_remoto(git, repo)
    if valor == PUSH_ANULADO:
        return None
    return ("AVISO: el remoto origin todavía acepta push por defecto. Anúlalo con "
            f"`git remote set-url --push origin {PUSH_ANULADO}` (publica con la URL completa).")


def _hallazgo(hallazgos: list[Hallazgo], nombre: str) -> Hallazgo | None:
    return next((h for h in hallazgos if h.herramienta == nombre), None)


def _armar_config(hallazgos: list[Hallazgo]) -> dict:
    datos = json.loads(EJEMPLO_CONFIG.read_text(encoding="utf-8"))
    claude = _hallazgo(hallazgos, "claude")
    git = _hallazgo(hallazgos, "git")
    if claude and claude.ruta:
        datos.setdefault("agentes", {}).setdefault("cc", {})["ejecutable"] = claude.ruta
    if git and git.ruta:
        datos.setdefault("herramientas", {})["git"] = git.ruta
    return datos


def _diff_config(existente: dict, detectado: dict) -> list[str]:
    pendientes = []
    ruta_cc = (detectado.get("agentes") or {}).get("cc", {}).get("ejecutable")
    actual_cc = (existente.get("agentes") or {}).get("cc", {}).get("ejecutable")
    if ruta_cc and actual_cc != ruta_cc:
        pendientes.append(f"revisar agentes.cc.ejecutable en config.json (detectado: {ruta_cc})")
    ruta_git = (detectado.get("herramientas") or {}).get("git")
    actual_git = (existente.get("herramientas") or {}).get("git")
    if ruta_git and actual_git != ruta_git:
        pendientes.append(f"revisar herramientas.git en config.json (detectado: {ruta_git})")
    return pendientes


def planear(aplicar: bool = False, *, repo: Path = INSTALACION, raiz: Path | None = None,
            cowork: Path | None = None, escritorio: Path | None = None, python_exe: str | None = None,
            bases: dict[str, Path] | None = None, ejecutar=None, entorno_base=None) -> Plan:
    """Calcula el plan. Con aplicar=True ejecuta solo los pasos en 'crearía'."""
    bases = bases or _bases(entorno_base)
    hallazgos = detectar(bases, ejecutar=ejecutar, entorno_base=entorno_base)
    plan = Plan(hallazgos=hallazgos)
    home = bases["USERPROFILE"]
    raiz = Path(raiz) if raiz is not None else home / ".orquestador"
    cowork = Path(cowork) if cowork is not None else home / "Orquestador-Cowork"
    escritorio = Path(escritorio) if escritorio is not None else acceso.escritorio_real()
    python_exe = python_exe or sys.executable
    repo = Path(repo)

    # Informe de herramientas
    for h in hallazgos:
        if h.ruta is None:
            plan.pasos.append(Paso(h.herramienta, "falta", h.detalle or "no encontrado",
                                   pendiente=(f"instalar {h.herramienta}" +
                                              (f" (ruta esperada: {h.detalle.split('se esperaba ', 1)[-1]})"
                                               if "se esperaba" in (h.detalle or "") else ""))))
        elif h.herramienta == "cursor":
            plan.pasos.append(Paso("cursor", "ya estaba", f"{h.ruta} ({h.detalle})"))
        elif h.sesion == "sin sesión":
            plan.pasos.append(Paso(h.herramienta, "revisar",
                                   f"{h.ruta}" + (f" {h.version}" if h.version else "") + ": sin sesión",
                                   pendiente=("claude auth login" if h.herramienta == "claude" else
                                              "codex login" if h.herramienta == "codex" else None)))
        else:
            detalle = h.ruta + (f" {h.version}" if h.version else "")
            if h.sesion:
                detalle += f" ({h.sesion})"
            if h.detalle:
                detalle += f" · {h.detalle}"
            plan.pasos.append(Paso(h.herramienta, "ya estaba" if h.ruta else "falta", detalle.strip(" ·")))

    # Raíz de estado
    if raiz.is_dir():
        plan.pasos.append(Paso("raiz", "ya estaba", str(raiz)))
    elif aplicar:
        raiz.mkdir(parents=True, exist_ok=True)
        plan.pasos.append(Paso("raiz", "creado", str(raiz)))
    else:
        plan.pasos.append(Paso("raiz", "crearía", str(raiz)))

    # config.json
    config_ruta = raiz / "config.json"
    detectado = _armar_config(hallazgos)
    if config_ruta.is_file():
        try:
            existente = json.loads(config_ruta.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError):
            existente = {}
        diffs = _diff_config(existente if isinstance(existente, dict) else {}, detectado)
        plan.pasos.append(Paso("config", "ya estaba", str(config_ruta),
                               pendiente="; ".join(diffs) if diffs else None))
        for d in diffs:
            plan.pendientes.append(d)
    elif aplicar:
        raiz.mkdir(parents=True, exist_ok=True)
        config_ruta.write_text(json.dumps(detectado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        plan.pasos.append(Paso("config", "creado", str(config_ruta)))
    else:
        plan.pasos.append(Paso("config", "crearía", str(config_ruta)))

    # Carpeta Cowork
    if cowork.is_dir():
        plan.pasos.append(Paso("cowork", "ya estaba", str(cowork)))
    elif aplicar:
        cowork.mkdir(parents=True, exist_ok=True)
        plan.pasos.append(Paso("cowork", "creado", str(cowork)))
    else:
        plan.pasos.append(Paso("cowork", "crearía", str(cowork)))

    # Acceso directo
    try:
        acceso.contenido_acceso_directo(repo, python_exe)  # valida rutas
        rutas_ok, motivo_cmd = True, None
    except ValueError as e:
        rutas_ok, motivo_cmd = False, str(e)
    destino_cmd = escritorio / "Orquestador.cmd"
    if not rutas_ok:
        plan.pasos.append(Paso("acceso-directo", "revisar", motivo_cmd or "rutas inválidas",
                               pendiente=motivo_cmd))
    elif destino_cmd.is_file() and acceso.MARCA_CMD.encode("ascii") not in destino_cmd.read_bytes():
        plan.pasos.append(Paso("acceso-directo", "revisar",
                               f"ya existe {destino_cmd} y no lo generó el orquestador; no se tocó",
                               pendiente=f"revisar o renombrar {destino_cmd}"))
    elif aplicar:
        existia = destino_cmd.is_file()
        antes = destino_cmd.read_bytes() if existia else None
        ruta, motivo = acceso.generar_acceso_directo(escritorio, repo, python_exe)
        if motivo:
            plan.pasos.append(Paso("acceso-directo", "revisar", motivo, pendiente=motivo))
        elif existia and antes == destino_cmd.read_bytes():
            plan.pasos.append(Paso("acceso-directo", "ya estaba", str(ruta)))
        else:
            plan.pasos.append(Paso("acceso-directo", "creado", str(ruta)))
    elif destino_cmd.is_file() and acceso.MARCA_CMD.encode("ascii") in destino_cmd.read_bytes():
        esperado = acceso._bytes_cmd(acceso.contenido_acceso_directo(repo, python_exe))
        estado = "ya estaba" if destino_cmd.read_bytes() == esperado else "crearía"
        detalle = str(destino_cmd) if estado == "ya estaba" else f"actualizaría {destino_cmd}"
        plan.pasos.append(Paso("acceso-directo", estado, detalle))
    else:
        plan.pasos.append(Paso("acceso-directo", "crearía", str(destino_cmd)))

    # Remoto sin push (solo lectura; nunca se cambia git desde aquí)
    git_h = _hallazgo(hallazgos, "git")
    git_exe = git_h.ruta if git_h and git_h.ruta else None
    valor_push = pushurl_del_remoto(git_exe, repo) if git_exe else None
    if git_exe and valor_push is None and hay_origin(git_exe, repo) is False:
        plan.push_anulado = None
        plan.pasos.append(Paso("remoto-push", "ya estaba", "sin remoto origin: no hay push que anular"))
    elif valor_push == PUSH_ANULADO:
        plan.push_anulado = True
        plan.pasos.append(Paso("remoto-push", "ya estaba", "push por defecto anulado"))
    elif git_exe:
        plan.push_anulado = False
        cmd = f"git remote set-url --push origin {PUSH_ANULADO}"
        plan.pasos.append(Paso("remoto-push", "revisar", "push por defecto habilitado", pendiente=cmd))
    else:
        plan.push_anulado = None
        plan.pasos.append(Paso("remoto-push", "falta", "sin git para revisar el remoto"))

    _completar_pendientes(plan)
    return plan


def _completar_pendientes(plan: Plan) -> None:
    """Lista numerada: fijos + los que salieron de los pasos. Sin duplicar."""
    vistos = set(plan.pendientes)
    for p in plan.pasos:
        if p.pendiente and p.pendiente not in vistos:
            plan.pendientes.append(p.pendiente)
            vistos.add(p.pendiente)
    fijos = [
        r"conectar Orquestador-Cowork\<proyecto> en Cowork (solo esa carpeta)",
        "py -3.12 .\\orq.py proyecto nuevo <nombre> --repo <ruta>",
        "correr docs/verificacion-manual.md (pasos 1 a 7)",
    ]
    if plan.push_anulado is False:
        cmd = f"git remote set-url --push origin {PUSH_ANULADO}"
        if cmd not in vistos:
            # ya debería estar desde el paso; si no, se agrega
            pass
    for f in fijos:
        if f not in vistos:
            plan.pendientes.append(f)
            vistos.add(f)


def describir(plan: Plan, aplicado: bool) -> str:
    lineas = ["Instalación aplicada:" if aplicado else "Simulación (no se escribió nada):"]
    for p in plan.pasos:
        lineas.append(f"  [{p.estado}] {p.nombre}: {p.detalle}")
    lineas.append("")
    lineas.append("Pendientes:")
    if not plan.pendientes:
        lineas.append("  (ninguno)")
    else:
        for i, texto in enumerate(plan.pendientes, 1):
            lineas.append(f"  {i}. {texto}")
    if not aplicado:
        lineas.append("")
        lineas.append("Usa --aplicar para crear lo que falta. No pisa config.json ni un .cmd ajenos.")
    return "\n".join(lineas)


def instalar(aplicar: bool = False, **kwargs) -> Plan:
    """Punto de entrada: planear y, si se pide, aplicar los pasos 'crearía'."""
    return planear(aplicar, **kwargs)
