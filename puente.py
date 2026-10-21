"""Puente entre Claude (Cowork) y Claude Code en el PC de Sebastian.

Claude deja trabajos en trabajos/pendientes/*.json. Este script los toma de a uno, prepara el worktree
del cambio si hace falta, corre Claude Code sin ventana (claude -p) con permisos fijos y escribe la
respuesta en trabajos/hechos/. No ejecuta comandos que vengan en el trabajo: solo le pasa el prompt a
Claude Code. Las acciones de git (commit, archive, merge) están apagadas salvo que config.json las permita.

Uso:
  py -3.12 puente.py            corre en bucle (revisa la carpeta cada `intervalo_segundos`)
  py -3.12 puente.py --una-vez  procesa lo pendiente y termina
Solo librería estándar.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

AQUI = Path(__file__).resolve().parent
PENDIENTES = AQUI / "trabajos" / "pendientes"
EN_CURSO = AQUI / "trabajos" / "en_curso"
HECHOS = AQUI / "trabajos" / "hechos"
SESIONES = AQUI / "sesiones.json"
ESTADO = AQUI / "estado.json"
REGISTRO = AQUI / "registro.log"
CANDADO = AQUI / ".puente.lock"

NOMBRE_OK = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}$")
ID_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,100}$")
CLAVES = {"id", "tipo", "cambio", "rama", "base", "prompt", "nueva_sesion", "timeout_min", "acciones", "mensaje",
          "no_antes_de", "reintentos", "repo"}
LIMITE = ("session limit", "usage limit", "limit · resets", "rate limit")


def ahora() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def log(texto: str) -> None:
    with REGISTRO.open("a", encoding="utf-8") as f:
        f.write(f"{ahora()} {texto}\n")


def leer_json(ruta: Path, defecto):
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return defecto


def escribir_json(ruta: Path, datos) -> None:
    tmp = ruta.with_suffix(ruta.suffix + ".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, ruta)


def config() -> dict:
    c = leer_json(AQUI / "config.json", None)
    if c is None:
        raise SystemExit("falta config.json junto a puente.py")
    return c


def run(cmd: list[str], cwd: Path, timeout: int = 600, entrada: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd), input=entrada, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, env={**os.environ, "PYTHONIOENCODING": "utf-8"})


def validar(t: dict) -> str | None:
    desconocidas = set(t) - CLAVES
    if desconocidas:
        return f"claves desconocidas: {sorted(desconocidas)}"
    if not ID_OK.match(str(t.get("id", ""))):
        return "id inválido"
    if t.get("tipo") not in ("cc", "git"):
        return "tipo debe ser cc o git"
    if not NOMBRE_OK.match(str(t.get("cambio", ""))):
        return "cambio inválido (minúsculas, números y guiones)"
    if t.get("rama") is not None and not NOMBRE_OK.match(str(t["rama"])):
        return "rama inválida"
    if t.get("repo") is not None and t["repo"] not in config().get("repos", {}):
        return "repo no está en la lista repos de config.json"
    if t.get("base") is not None and not re.match(r"^[A-Za-z0-9._/-]{1,80}$", str(t["base"])):
        return "base inválida"
    if t["tipo"] == "cc" and not str(t.get("prompt", "")).strip():
        return "falta prompt"
    if t["tipo"] == "git":
        acciones = t.get("acciones") or []
        if not acciones or any(a not in ("commit", "archive", "merge-main") for a in acciones):
            return "acciones de git permitidas: commit, archive, merge-main"
    return None


def repo_de(c: dict, t: dict) -> Path:
    """Repo del trabajo: el por defecto, o uno de la lista `repos` de config.json (nunca una ruta libre)."""
    return Path(c["repos"][t["repo"]]) if t.get("repo") else Path(c["repo"])


def clave_sesion(t: dict) -> str:
    return f"{t['repo']}:{t['cambio']}" if t.get("repo") else t["cambio"]


def worktree(c: dict, t: dict) -> Path:
    repo = repo_de(c, t)
    destino = repo.parent / f"wt-{t['cambio']}"
    if destino.exists():
        return destino
    rama = t.get("rama") or t["cambio"]
    base = t.get("base") or "main"
    existe = run(["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{rama}"], repo).returncode == 0
    cmd = ["git", "worktree", "add", str(destino), rama] if existe else ["git", "worktree", "add", str(destino), "-b", rama, base]
    r = run(cmd, repo)
    if r.returncode != 0:
        raise RuntimeError(f"git worktree add falló: {r.stderr.strip()}")
    log(f"worktree creado {destino} ({'rama existente' if existe else 'rama nueva desde ' + base})")
    return destino


def ajustes_cc(c: dict, wt: Path) -> Path:
    """Archivo de ajustes que se pasa con --settings: permisos fijos, nunca bypass."""
    ruta = AQUI / "trabajos" / "ajustes_cc.json"
    escribir_json(ruta, {"permissions": {"defaultMode": "dontAsk", "allow": c["permitir"], "deny": c["denegar"],
                                         "additionalDirectories": c.get("directorios_extra", [])}})
    return ruta


def correr_cc(c: dict, t: dict) -> dict:
    wt = worktree(c, t)
    sesiones = leer_json(SESIONES, {})
    sid = None if t.get("nueva_sesion") else sesiones.get(clave_sesion(t))
    claude = shutil.which(c.get("claude", "claude")) or c.get("claude", "claude")
    cmd = [claude, "-p", "--output-format", "json", "--settings", str(ajustes_cc(c, wt)), "--permission-mode", "dontAsk"]
    if sid:
        cmd += ["--resume", sid]
    minutos = int(t.get("timeout_min") or c.get("timeout_min", 90))
    log(f"{t['id']}: claude -p en {wt.name} (sesión {'nueva' if not sid else sid[:8]}), límite {minutos} min")
    inicio = time.time()
    r = run(cmd, wt, timeout=minutos * 60, entrada=t["prompt"])
    salida = {"codigo": r.returncode, "segundos": round(time.time() - inicio), "worktree": str(wt)}
    try:
        datos = json.loads(r.stdout)
        salida.update({k: datos.get(k) for k in ("session_id", "is_error", "num_turns", "total_cost_usd", "subtype")})
        texto = datos.get("result") or ""
        if datos.get("session_id"):
            sesiones[clave_sesion(t)] = datos["session_id"]
            escribir_json(SESIONES, sesiones)
    except json.JSONDecodeError:
        texto = r.stdout
    if r.stderr.strip():
        salida["stderr"] = r.stderr.strip()[-4000:]
    return {"meta": salida, "texto": texto}


def correr_git(c: dict, t: dict) -> dict:
    if not c.get("permitir_git"):
        return {"meta": {"codigo": 1, "error": "acciones de git apagadas en config.json (permitir_git: false)"}, "texto": ""}
    repo = repo_de(c, t)
    wt = repo.parent / f"wt-{t['cambio']}"
    rama = t.get("rama") or t["cambio"]
    pasos = []
    for accion in t["acciones"]:
        if accion == "commit":
            mensaje = str(t.get("mensaje") or "").strip()
            if not mensaje:
                return {"meta": {"codigo": 1, "error": "commit sin mensaje"}, "texto": "\n".join(pasos)}
            for cmd in (["git", "add", "-A"], ["git", "commit", "-m", mensaje]):
                r = run(cmd, wt)
                pasos.append(f"$ {' '.join(cmd[:3])}...\n{r.stdout}{r.stderr}")
                if r.returncode != 0:
                    return {"meta": {"codigo": r.returncode, "paso": accion}, "texto": "\n".join(pasos)}
        elif accion == "archive":
            r = run(["openspec", "archive", t["cambio"], "--yes"], wt)
            pasos.append(f"$ openspec archive {t['cambio']}\n{r.stdout}{r.stderr}")
            if r.returncode != 0:
                return {"meta": {"codigo": r.returncode, "paso": accion}, "texto": "\n".join(pasos)}
        elif accion == "merge-main":
            r = run(["git", "merge", "--ff-only", rama], repo)
            pasos.append(f"$ git merge --ff-only {rama} (en repo)\n{r.stdout}{r.stderr}")
            if r.returncode != 0:
                return {"meta": {"codigo": r.returncode, "paso": accion}, "texto": "\n".join(pasos)}
    return {"meta": {"codigo": 0}, "texto": "\n".join(pasos)}


def procesar(c: dict, archivo: Path) -> None:
    en_curso = EN_CURSO / archivo.name
    os.replace(archivo, en_curso)
    base = en_curso.stem
    t_ok, t = False, {}
    try:
        t = json.loads(en_curso.read_text(encoding="utf-8"))
        error = validar(t) if isinstance(t, dict) else "el trabajo no es un objeto JSON"
        if error:
            res = {"meta": {"codigo": 2, "error": error}, "texto": ""}
        else:
            base, t_ok = t["id"], True
            escribir_json(ESTADO, {"vivo": ahora(), "trabajando_en": t["id"]})
            res = correr_cc(c, t) if t["tipo"] == "cc" else correr_git(c, t)
    except subprocess.TimeoutExpired:
        res = {"meta": {"codigo": 124, "error": "se acabó el tiempo del trabajo"}, "texto": ""}
    except Exception as e:  # noqa: BLE001 - el puente nunca se cae por un trabajo
        res = {"meta": {"codigo": 1, "error": f"{type(e).__name__}: {e}", "traza": traceback.format_exc()[-2000:]}, "texto": ""}
    if t_ok and res["meta"].get("is_error") and any(m in (res["texto"] or "").lower() for m in LIMITE) \
            and int(t.get("reintentos", 0)) < 6:
        # Límite de uso del plan: el trabajo vuelve a la cola y se reintenta en 30 minutos, sin perder la sesión.
        t["reintentos"] = int(t.get("reintentos", 0)) + 1
        t["no_antes_de"] = (dt.datetime.now().astimezone() + dt.timedelta(minutes=30)).isoformat(timespec="seconds")
        escribir_json(PENDIENTES / archivo.name, t)
        en_curso.unlink(missing_ok=True)
        log(f"{base}: límite de uso del plan; reintento {t['reintentos']} desde {t['no_antes_de']}")
        return
    res["meta"]["terminado"] = ahora()
    (HECHOS / f"{base}.md").write_text(res["texto"] or "", encoding="utf-8")
    escribir_json(HECHOS / f"{base}.resultado.json", res["meta"])
    os.replace(en_curso, HECHOS / f"{base}.trabajo.json")
    log(f"{base}: terminado con código {res['meta'].get('codigo')}")


def tomar_candado() -> bool:
    try:
        fd = os.open(CANDADO, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        viejo = time.time() - CANDADO.stat().st_mtime
        if viejo > 6 * 3600:  # candado abandonado (PC apagado a la mitad)
            CANDADO.unlink(missing_ok=True)
            return tomar_candado()
        return False


def main() -> None:
    for d in (PENDIENTES, EN_CURSO, HECHOS):
        d.mkdir(parents=True, exist_ok=True)
    if not tomar_candado():
        print("ya hay un puente corriendo (.puente.lock)")
        return
    una_vez = "--una-vez" in sys.argv
    log("puente iniciado" + (" (una vez)" if una_vez else ""))
    try:
        # Lo que quedó a medias por un corte vuelve a pendientes.
        for f in EN_CURSO.glob("*.json"):
            os.replace(f, PENDIENTES / f.name)
        while True:
            c = config()
            for archivo in sorted(PENDIENTES.glob("*.json")):
                try:
                    espera = json.loads(archivo.read_text(encoding="utf-8")).get("no_antes_de")
                except (OSError, json.JSONDecodeError, AttributeError):
                    espera = None
                if espera and dt.datetime.fromisoformat(espera) > dt.datetime.now().astimezone():
                    continue
                procesar(c, archivo)
            escribir_json(ESTADO, {"vivo": ahora(), "trabajando_en": None})
            os.utime(CANDADO)
            if una_vez:
                break
            time.sleep(int(c.get("intervalo_segundos", 20)))
    finally:
        CANDADO.unlink(missing_ok=True)
        log("puente detenido")


if __name__ == "__main__":
    main()
