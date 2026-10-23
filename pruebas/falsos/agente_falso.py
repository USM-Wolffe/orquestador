"""Ejecutable falso de agentes para las pruebas (E1: solo `--como cc`). Nunca usa la red ni lee credenciales.

Imita `claude -p --output-format stream-json --verbose`: lee el prompt por stdin y emite NDJSON.
Fuentes del formato que imitan los guiones:
- code.claude.com/docs/en/headless: stream-json, `system/init` primero y `result` al final.
- code.claude.com/docs/en/agent-sdk/typescript: SDKSystemMessage (init), SDKAssistantMessage (text, tool_use,
  `error: "rate_limit"`), SDKUserMessage (tool_result), SDKResultMessage (`subtype`, `is_error`, `result`,
  `errors`, `usage`, `total_cost_usd`, `permission_denials`, `session_id`) y SDKRateLimitEvent
  (`rate_limit_info.status`, `resetsAt`).
- code.claude.com/docs/en/errors: "You've hit your session limit · resets 3:45pm".
- "No conversation found with session ID" al retomar una sesión que no existe: texto supuesto (no documentado),
  ajustable aquí si el binario real dice otra cosa.

Cómo elegir el guion: una línea `#guion: <nombre>` en el prompt, o la variable ORQ_FALSO_GUION (por defecto `ok`).
Traza: si existe ORQ_FALSO_TRAZA, agrega una línea JSON con argv, stdin, carpeta, nombres (nunca valores) de las
variables de entorno, PATH y el contenido del archivo de `--settings`.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time

USO = {"input_tokens": 1200, "output_tokens": 340, "cache_creation_input_tokens": 50, "cache_read_input_tokens": 800}


def valor(args: list[str], bandera: str) -> str | None:
    if bandera in args:
        i = args.index(bandera)
        return args[i + 1] if i + 1 < len(args) else None
    return None


_SALIDA_JSON: list | None = None  # con `--output-format json` (puente v0) solo se imprime el `result` al final


def emitir(obj: dict) -> None:
    if _SALIDA_JSON is not None:
        _SALIDA_JSON.append(obj)
        return
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _marca_una_vez(nombre: str) -> bool:
    """True la primera vez que se llama con `nombre` en la prueba (marca junto a la traza)."""
    traza = os.environ.get("ORQ_FALSO_TRAZA")
    if not traza:
        return True
    marca = f"{traza}.{nombre}"
    if os.path.exists(marca):
        return False
    with open(marca, "w", encoding="utf-8") as f:
        f.write("visto\n")
    return True


def trazar(registro: dict) -> None:
    ruta = os.environ.get("ORQ_FALSO_TRAZA")
    if ruta:
        with open(ruta, "a", encoding="utf-8") as f:
            f.write(json.dumps(registro, ensure_ascii=False) + "\n")


class Guion:
    def __init__(self, sesion: str, cwd: str, retomada: bool):
        self.sesion, self.cwd, self.retomada, self.n = sesion, cwd, retomada, 0
        self.tools = (valor(sys.argv, "--tools") or "Read,Edit,Write,Glob,Grep,Bash").split(",")
        self.mcp = []

    def init(self) -> None:  # SDKSystemMessage subtype init (doc agent-sdk/typescript)
        emitir({"type": "system", "subtype": "init", "session_id": self.sesion, "cwd": self.cwd,
                "model": "claude-sonnet-5-5", "permissionMode": "dontAsk", "apiKeySource": "none",
                "claude_code_version": "2.1.306", "tools": self.tools, "mcp_servers": self.mcp})

    def texto(self, texto: str, **extra) -> None:
        emitir({"type": "assistant", "session_id": self.sesion, "parent_tool_use_id": None,
                "message": {"role": "assistant", "content": [{"type": "text", "text": texto}]}, **extra})

    def herramienta(self, nombre: str, entrada: dict, resultado: str, error: bool = False) -> None:
        self.n += 1
        ident = f"toolu_falso_{self.n}"
        emitir({"type": "assistant", "session_id": self.sesion, "parent_tool_use_id": None,
                "message": {"role": "assistant", "content": [{"type": "tool_use", "id": ident, "name": nombre,
                                                               "input": entrada}]}})
        emitir({"type": "user", "session_id": self.sesion, "parent_tool_use_id": None,
                "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": ident,
                                                          "content": resultado, "is_error": error}]}})

    def resultado(self, texto: str, error: bool = False, subtipo: str = "success", **extra) -> None:
        cuerpo = {"type": "result", "subtype": subtipo, "is_error": error, "duration_ms": 1234,
                  "duration_api_ms": 1100, "num_turns": 3, "session_id": self.sesion, "total_cost_usd": 0.0421,
                  "usage": USO, "permission_denials": [], **extra}
        if subtipo == "success":
            cuerpo["result"] = texto
        else:
            cuerpo["errors"] = [texto]
        emitir(cuerpo)


def guion_ok(g: Guion) -> int:
    # Corrida típica de la spec eventos-actividad: edita app.py, corre las pruebas, responde y termina.
    g.init()
    with open(os.path.join(g.cwd, "app.py"), "w", encoding="utf-8") as f:
        f.write("print('hola sintético')\n")
    g.herramienta("Edit", {"file_path": os.path.join(g.cwd, "app.py"), "old_string": "", "new_string": "x"},
                  "The file app.py has been updated.")
    emitir({"type": "evento_futuro", "detalle": "un tipo que el adaptador no conoce"})
    g.herramienta("Bash", {"command": "py -3.12 -m unittest", "description": "corre las pruebas"}, "OK")
    final = "Listo: edité app.py y las pruebas pasan."
    g.texto(final)
    g.resultado(final)
    return 0


def guion_lectura(g: Guion) -> int:
    g.init()
    g.herramienta("Read", {"file_path": os.path.join(g.cwd, "datos", "clientes.csv")},
                  "rut;nombre\n1-9;Cliente Sintético")
    g.texto("Leí el archivo de datos.")
    g.resultado("Leí el archivo de datos.")
    return 0


def guion_negado(g: Guion) -> int:
    g.init()
    g.texto("No me dejaron publicar.")
    g.resultado("No me dejaron publicar.", permission_denials=[
        {"tool_name": "Bash", "tool_use_id": "toolu_negado", "tool_input": {"command": "git push origin main"}}])
    return 0


def guion_limite(g: Guion) -> int:
    # SDKRateLimitEvent con status rejected y resetsAt (doc agent-sdk/typescript); texto de doc errors.
    g.init()
    emitir({"type": "rate_limit_event", "session_id": g.sesion,
            "rate_limit_info": {"status": "rejected", "resetsAt": int(time.time()) + 3600}})
    g.texto("You've hit your session limit · resets 6pm", error="rate_limit")
    g.resultado("You've hit your session limit · resets 6pm", error=True, subtipo="error_during_execution")
    return 1


def guion_uso_plan(g: Guion) -> int:
    g.init()
    emitir({"type": "rate_limit_event", "session_id": g.sesion,
            "rate_limit_info": {"status": "allowed_warning", "utilization": 62,
                                "resetsAt": int(time.time()) + 3600}})
    g.texto("Listo con uso del plan.")
    g.resultado("Listo con uso del plan.")
    return 0


def guion_limite_texto(g: Guion) -> int:
    g.init()
    emitir({"type": "result", "subtype": "success", "is_error": True, "session_id": g.sesion, "duration_ms": 10,
            "result": "You've hit your session limit · resets 3:45pm", "usage": USO, "total_cost_usd": 0})
    return 1


def guion_edita_y_espera(g: Guion) -> int:
    # Spec tablero, "Diff durante la ejecución": crea un archivo nuevo y sigue trabajando.
    g.init()
    os.makedirs(os.path.join(g.cwd, "src"), exist_ok=True)
    with open(os.path.join(g.cwd, "src", "nuevo.py"), "w", encoding="utf-8") as f:
        f.write("a = 1\nb = 2\n")
    g.herramienta("Write", {"file_path": os.path.join(g.cwd, "src", "nuevo.py"), "content": "a = 1\nb = 2\n"},
                  "File created successfully")
    time.sleep(600)
    return 0


def guion_limite_una_vez(g: Guion) -> int:
    return guion_limite(g) if _marca_una_vez("limite") else guion_ok(g)


def guion_colgado_una_vez(g: Guion) -> int:
    return guion_colgado(g) if _marca_una_vez("colgado") else guion_ok(g)


def guion_secretos(g: Guion) -> int:
    # Spec estado-cowork, "Secretos sembrados": un comando con un token y un stderr con un secreto sin formato
    # conocido (no lo atrapa la redacción por patrones: solo lo protege la lista blanca de la salida).
    g.init()
    g.herramienta("Bash", {"command": "GH_TOKEN=ghp_COMANDOSINTETICO0123456789abcd git ls-remote origin"},
                  "salida del comando con ghp_COMANDOSINTETICO0123456789abcd")
    sys.stderr.write("fallo al conectar; clave del cliente: SECRETO-STDERR-7731\n")
    sys.stderr.flush()
    return 1


def guion_limite_sin_hora(g: Guion) -> int:
    # Texto de límite sin hora de reinicio (la que trae el v0 en puente.py).
    g.init()
    sys.stderr.write("Claude AI usage limit reached\n")
    sys.stderr.flush()
    return 1


def guion_error(g: Guion) -> int:
    g.init()
    g.resultado("fallo sintético del agente", error=True, subtipo="error_during_execution")
    return 1


def guion_sin_final(g: Guion) -> int:
    g.init()
    sys.stderr.write("Error: se rompió algo. clave=sk-ant-api03-SECRETOSINTETICO0123456789\n")
    sys.stderr.flush()
    return 2


def guion_colgado(g: Guion) -> int:
    g.init()
    time.sleep(600)
    return 0


def guion_hijo_largo(g: Guion) -> int:
    g.init()
    hijo = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    trazar({"hijo": hijo.pid})
    time.sleep(600)
    return 0


def guion_sesion_inexistente(g: Guion) -> int:
    if g.retomada:
        emitir({"type": "result", "subtype": "error_during_execution", "is_error": True, "session_id": g.sesion,
                "errors": [f"No conversation found with session ID: {g.sesion}"]})
        return 1
    return guion_ok(g)


def guion_intenta_commit(g: Guion) -> int:
    # El agente "desobedece": hace un commit de verdad en el repo sintético de la prueba.
    g.init()
    git = shutil.which("git")
    with open(os.path.join(g.cwd, "intruso.txt"), "w", encoding="utf-8") as f:
        f.write("cambio sintético\n")
    entorno = {**os.environ, "GIT_AUTHOR_NAME": "Falso", "GIT_AUTHOR_EMAIL": "falso@example.invalid",
               "GIT_COMMITTER_NAME": "Falso", "GIT_COMMITTER_EMAIL": "falso@example.invalid"}
    subprocess.run([git, "add", "intruso.txt"], cwd=g.cwd, env=entorno, capture_output=True)
    subprocess.run([git, "commit", "-q", "-m", "commit no autorizado"], cwd=g.cwd, env=entorno, capture_output=True)
    g.herramienta("Bash", {"command": "git commit -m 'commit no autorizado'"}, "[login abc123] commit no autorizado")
    g.resultado("Hice un commit.")
    return 0


def guion_seguridad(g, nombre):
    hijo = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    trazar({"hijo": hijo.pid})
    if nombre == "conectores":
        g.tools.append("mcp__claude_ai_Google_Drive__share_file")
    if nombre == "mcp_pendiente":
        g.mcp = [{"name": "servidor_sintetico", "status": "pending"}]
    if nombre != "sin_init":
        g.init()
    if nombre == "herramienta_tarde":
        g.herramienta("mcp__claude_ai_Gamma__generate", {}, "sintético")
    if nombre == "sin_init":  # una herramienta pedida: lo único que debe cortar es la falta del aviso de inicio
        g.herramienta("Read", {"file_path": os.path.join(g.cwd, "app.py")}, "sintético")
    if nombre == "forma_inesperada":  # `message` como texto y no como objeto: el lector no puede revisarlo
        emitir({"type": "assistant", "session_id": g.sesion, "parent_tool_use_id": None, "message": "texto suelto"})
    g.resultado("Listo")
    time.sleep(30)  # el corte debe matar al falso, sin esperar su salida natural
    return 0


GUIONES = {n: (lambda g, n=n: guion_seguridad(g, n)) for n in
           ("conectores", "mcp_pendiente", "herramienta_tarde", "sin_init", "forma_inesperada")}
GUIONES.update({"ok": guion_ok, "uso_plan": guion_uso_plan, "lectura": guion_lectura, "negado": guion_negado, "limite": guion_limite,
           "limite_texto": guion_limite_texto, "limite_sin_hora": guion_limite_sin_hora, "error": guion_error, "sin_final": guion_sin_final,
           "colgado": guion_colgado, "hijo_largo": guion_hijo_largo, "sesion_inexistente": guion_sesion_inexistente,
           "intenta_commit": guion_intenta_commit, "limite_una_vez": guion_limite_una_vez,
           "colgado_una_vez": guion_colgado_una_vez, "secretos": guion_secretos,
           "edita_y_espera": guion_edita_y_espera})


def main() -> int:
    global _SALIDA_JSON
    args = sys.argv[1:]
    if "--version" in args:
        print(os.environ.get("ORQ_FALSO_VERSION", "2.1.306 (Claude Code)"))
        return 0
    if valor(args, "--output-format") == "json":
        _SALIDA_JSON = []
        codigo = _correr(args)
        finales = [e for e in _SALIDA_JSON if e.get("type") == "result"]
        if finales:
            final = dict(finales[-1])
            if "result" not in final and final.get("errors"):
                final["result"] = "\n".join(str(x) for x in final["errors"])  # lo que lee el puente v0
            sys.stdout.write(json.dumps(final, ensure_ascii=False))
            sys.stdout.flush()
        return codigo
    return _correr(args)


def _correr(args: list[str]) -> int:
    prompt = sys.stdin.read()
    m = re.search(r"^#guion:\s*(\S+)", prompt, re.MULTILINE)
    nombre = m.group(1) if m else os.environ.get("ORQ_FALSO_GUION", "ok")
    ajustes = valor(args, "--settings")
    contenido_ajustes = None
    if ajustes and os.path.isfile(ajustes):
        with open(ajustes, encoding="utf-8") as f:
            contenido_ajustes = json.load(f)
    trazar({"argv": args, "stdin": prompt, "cwd": os.getcwd(), "env_claves": sorted(os.environ),
            "path": os.environ.get("PATH", ""), "pid": os.getpid(), "guion": nombre, "settings": contenido_ajustes})
    # El puente v0 no pasa --session-id: como el binario real, el falso abre una sesión nueva con su propio id.
    sesion = valor(args, "--resume") or valor(args, "--session-id") or "0f0e0d0c-0b0a-4000-8000-00000000c0de"
    guion = GUIONES.get(nombre)
    if guion is None:
        sys.stderr.write(f"guion desconocido: {nombre}\n")
        return 3
    return guion(Guion(sesion, os.getcwd(), "--resume" in args))


if __name__ == "__main__":
    sys.exit(main())
