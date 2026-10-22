# Diseño del orquestador multiagente (referencia)

**Estado:** aprobado por Sebastian como referencia el 22-10-2026. Se implementa por etapas (`docs/etapas.md`).

Cómo leer este documento:
- Cada sección lleva la etapa en que entra: **[E1]**, **[E2]**, **[E3]** o **[E4]**.
- Lo de E1 es el change `openspec/changes/orquestador-v1`. Sus specs y su `design.md` mandan sobre este
  documento si difieren.
- Los requisitos de E2 a E4 salieron del change y quedan textuales en `docs/referencia/requisitos-e2-e4.md`.
  Cada change de E2, E3 y E4 los toma de ahí.

## 0. Decisiones de Sebastian (22-10-2026)

1. **Etapas.** El diseño completo se aprueba como referencia, pero se implementa en 4 changes:
   - E1: registro de tareas, eventos, tablero, adaptador cc y compatibilidad v0.
   - E2: adaptador codex.
   - E3: paridad de capacidades y `doctor`.
   - E4: adaptador cursor.
2. **Gates.** Se aprueban con un **botón en el tablero**, no con `orq gate`. El tablero deja de ser de solo
   lectura solo para esa acción (sección 5).
3. **Cowork lee el estado** (tareas, eventos, resultados y consumo) además de escribir solicitudes (sección 11).
4. **Recomendaciones aceptadas:** decisiones 1, 2, 3, 5, 8, 11, 12, 13, 14, 15, 16, 17 y 18 (sección 18).
   La 10 queda reemplazada por el punto 2.
5. **Credenciales de WatchGuard.** `~/.embudo` sigue donde está. Queda como riesgo abierto (sección 19).

## 1. Contexto [todas]

- **`puente.py` (v0)** corre un trabajo a la vez:
  - `claude -p --output-format json` con permisos `dontAsk`, con listas `permitir`/`denegar` en un `--settings`
    generado.
  - Sesión por cambio en `sesiones.json` y worktree `..\wt-<cambio>`.
  - Reencola a 30 minutos cuando detecta el límite del plan por texto.
  - Su seguridad descansa en las reglas de Claude Code; no hay sandbox de sistema operativo.
- **Plataforma**: Windows 11 Pro 10.0.26200, Python 3.12, solo librería estándar. Todo corre con el usuario de
  Sebastian: el orquestador, los agentes y Cowork (este último en su VM, con las carpetas que Sebastian conecta en
  la app).
- **Agentes en este PC** (al 21-10-2026): `claude` 2.1.306 instalado. `codex`, `agent` y `cursor-agent` no
  respondían en el `PATH` (`command not found`), así que sus flags salen de la documentación oficial y del código
  fuente publicado (sección 17). Nada se probó contra los binarios reales.
- **Rutas reales de instalación** que informó Sebastian el 22-10-2026, no verificadas por mí:
  - Codex: `%LOCALAPPDATA%\OpenAI\Codex\bin\<hash>\codex.exe`.
  - Cursor: `%LOCALAPPDATA%\cursor-agent\agent.ps1`.
- **Hechos de plataforma que cambian la seguridad**:
  - El sandbox de Bash de Claude Code funciona en macOS, Linux y WSL2. En Windows nativo, "Claude Code runs
    commands unsandboxed" (code.claude.com/docs/en/sandboxing).
  - Codex trae sandbox nativo en Windows en tres variantes: `mxc`, `elevated` y `unelevated`
    (learn.chatgpt.com/docs/windows/windows-sandbox).
  - El sandbox de Cursor no está documentado para Windows nativo; su blog dice que en Windows usa WSL2
    (cursor.com/blog/agent-sandboxing).

**Objetivos**:
- Un núcleo único (planificador, registro, eventos) y adaptadores intercambiables.
- La misma lista de controles para todos los agentes, con el nivel de garantía real escrito y visible.
- Sin dependencias fuera de la librería estándar, y pruebas sin red ni agentes reales.

**Fuera de alcance**:
- Commits, merges, archive o push hechos por el orquestador: siempre los hace Sebastian.
- Agentes en WSL2 o con una cuenta de Windows dedicada (decisión 6).
- Migrar el proyecto Embudo (change aparte, que decide Sebastian).

## 2. Procesos y módulos [E1]

- **`orq correr`** es el único proceso que escribe el estado. Su bucle se repite cada 2 s y en cada vuelta:
  1. Lee las entradas de Cowork, las solicitudes de `orq tarea` y las decisiones de gate que llegan del tablero.
  2. Aplica los resultados de las corridas.
  3. Recalcula los bloqueos.
  4. Lanza las tareas que caben.
  5. Reescribe la salida de Cowork.

  Cada corrida vive en su hilo, que lanza el agente, lee su salida, escribe eventos y le devuelve mensajes al
  bucle por una `queue.Queue`.
- **El tablero corre dentro de `orq correr`**, en un hilo aparte (cambió el 22-10-2026; antes era un proceso
  aparte). Así una decisión de gate viaja en memoria al bucle y no existe ningún archivo de decisiones de gate que
  otro programa pueda falsificar (sección 5). Con `orq correr --sin-tablero` no se levanta.
- **`orq tarea <p> <id> reintentar|cancelar`**, `orq proyecto nuevo`, `orq estado` e `orq importar-v0` son
  comandos cortos. Ninguno escribe `tareas.json`: `orq tarea` deja la solicitud en `decisiones\` y el bucle la
  aplica. **[E3]** `orq doctor` escribe solo `doctor.json`.
- **Módulos** (paquete `orquestador/`):
  - `config.py`, `registro.py`, `entrada.py`, `eventos.py`, `redaccion.py`, `salida_cowork.py`,
    `planificador.py`, `corrida.py`, `seguridad.py`, `worktrees.py` y `gates.py`.
  - `adaptadores/{base,cc}.py` en E1, `codex.py` en E2 y `cursor.py` en E4.
  - `tablero/` (servidor y estáticos) y, en **[E3]**, `capacidades.py`, `skills.py`, `contrato.py` y
    `doctor.py`.
- **Alternativa descartada**: un proceso por proyecto. Habría que coordinar entre procesos los límites globales
  y por agente, y el plan de cada agente es por cuenta.

## 3. Configuración y estado [E1, con agregados por etapa]

```
%USERPROFILE%\.orquestador\            raíz de estado (config "raiz_estado"; ORQ_RAIZ o --raiz)
  config.json                           global: límites, agentes (ruta absoluta del ejecutable, habilitado),
                                        herramientas (ruta absoluta de git), puerto del tablero, cowork_raiz
  agentes.json                          por agente: versión, ruta resuelta, disponible, agotado_hasta
  orquestador.lock / orquestador.json   candado de instancia (pid) / latido y versión
  doctor.json                           [E3] última revisión de paridad
  registro.log                          registro técnico
  proyectos\<p>\
    proyecto.json                       repo, base, carpeta de worktrees, agentes_permitidos, límites, red,
                                        gate_por_defecto, huellas aprobadas
                                        [E2] garantia_minima, traspaso  [E3] entorno, modelos, skills, mcp
    tareas.json (+ .bak)                fuente de verdad (solo escribe orq correr)
    sesiones.json                       "<cambio>|<agente>" → id de sesión
    decisiones\ (procesadas\)           solo reintentar/cancelar de `orq tarea`; NO gates
    eventos\eventos.jsonl (+ .1 … .5)
    diffstat\<id>.json
    corridas\<id>\<intento>\            perfil generado del agente y meta.json (pid, comando, hora)

%USERPROFILE%\Orquestador-Cowork\       carpeta de Cowork (config "cowork_raiz"), FUERA de la raíz de estado
  <p>\                                  lo único que Sebastian conecta en la app de Cowork
    entrada\ (procesadas\, rechazadas\) solicitudes de Cowork
    respuestas\                         acuse por solicitud
    salida\                             copia de solo lectura (sección 11)
```

- **Ya no existe `tablero.token`**. El token vive solo en memoria y se imprime en la terminal (sección 5).
- **`config.json` global (ejemplo E1)**:

  ```json
  {"limites": {"global": 2, "por_agente": {"cc": 1}},
   "agentes": {"cc": {"ejecutable": "C:\\Users\\<usuario>\\.local\\bin\\claude.exe", "habilitado": true}},
   "herramientas": {"git": "C:\\Program Files\\Git\\cmd\\git.exe"},
   "tablero": {"puerto": 8765}, "cowork_raiz": "C:\\Users\\<usuario>\\Orquestador-Cowork",
   "eventos": {"tope_mb": 10, "rotados": 5}}
  ```

  - **[E2]** agrega `"codex": {"buscar": "%LOCALAPPDATA%\\OpenAI\\Codex\\bin\\*\\codex.exe", "sandbox_windows":
    "elevated"}`.
  - **[E4]** agrega `"cursor": {"ejecutable": "%LOCALAPPDATA%\\cursor-agent\\agent.ps1", "habilitado": false}`.
- **Ejecutables por configuración, sin `PATH`** [E1]:
  - Cada agente y `git` se lanzan con la **ruta absoluta** de `config.json`. Al iniciar se valida que la ruta sea
    absoluta y exista; si no, el agente queda no disponible.
  - Al proceso del agente sí se le pasa un `PATH` filtrado del sistema, para que sus propias herramientas
    funcionen.
  - `orq proyecto nuevo` sugiere rutas candidatas buscando en ubicaciones conocidas (por ejemplo
    `%USERPROFILE%\.local\bin\claude.exe`), nunca en el `PATH`, y no escribe la config solo.
- **Proyecto**: `orq proyecto nuevo <nombre> --repo <ruta>` deja un `proyecto.json` con valores seguros: red
  apagada y `gate_por_defecto: true`.
- **Worktrees**: por defecto junto al repo, como en el v0 (`<padre del repo>\wt-<cambio>`).
- **Escrituras externas**: si alguien edita `tareas.json` por fuera, el bucle lo detecta por la huella de lo
  último que escribió. Conserva su versión, deja la ajena como `tareas.json.externo-<marca>` y registra el error.

## 4. Registro de tareas y máquina de estados [E1; campos de E2 y E3 marcados]

```json
{"id": "T-12", "titulo": "...", "prompt": "...",
 "agente": "cc", "agentes_permitidos": ["cc"], "estado": "pendiente", "motivo": "...",
 "dependencias": ["T-10"], "cambio": "login", "rama": "login", "base?": "main",
 "red": false, "prioridad": 100, "nueva_sesion": false, "timeout_min": 90, "no_antes_de": null,
 "gate": {"requiere": true, "motivo": "...", "decision": null, "nota": null, "en": null,
          "huella": null, "via": null},
 "intentos": 0, "max_intentos": 3, "interrupciones": 0, "limites_plan": 0,
 "resultado": {"ok": true, "resumen": "primeros 500 caracteres", "error": null, "codigo_salida": 0,
               "sesion": "...", "duracion_s": 812},
 "consumo": {"cc": {"tokens_entrada": 0, "tokens_salida": 0, "tokens_cache_lectura": 0,
                    "tokens_cache_escritura": 0, "costo_usd": 1.23, "costo_estimado": true, "segundos": 812}},
 "corridas": [{"intento": 1, "agente": "cc", "inicio": "...", "fin": "...", "ok": true, "clase_error": null}],
 "creada": "...", "actualizada": "...", "iniciada": "...", "terminada": "...",
 "historial": [{"de": null, "a": "pendiente", "por": "cowork", "en": "...", "motivo": "creada"}]}
```

- **[E2]** agrega `tipo` (`implementacion|revision`), `revisa`, `modo` (`escritura|lectura`) y `traspasos`.
- **[E3]** agrega `contrato` (objetivo, contexto, archivos, criterios_aceptacion, pruebas_esperadas, no_tocar,
  skills, respuesta), `modelo`, `esfuerzo`, `mcp`, y en `corridas` los campos `modelo_pedido`,
  `esfuerzo_pedido`, `modelo_efectivo`, `respuesta_valida` y `problemas_respuesta`.

Quién mueve cada transición: **O** = orquestador, **C** = Cowork (por la entrada), **S** = Sebastian (botón del
tablero para los gates; `orq tarea` para reintentar y cancelar).

```
            crear (C → O valida)
                   │
        ┌──────────┴───────────┐ deps abiertas / sin agente apto (O)
        ▼                      ▼
   [pendiente] ◄─────────── [bloqueada]
     │  ▲   deps hechas (O)    ▲
     │  └──── edición agrega dep abierta (C → O) ───────┘
     │ hay cupo, cambio libre, agente disponible (O)
     ▼
   [en_curso] ── límite de plan · interrupción · error con intentos (O) ──► [pendiente]
     │    ├── ok, gate requerido (O) ──► [esperando_gate] ── aprobar en el tablero (S) ──► [hecha]
     │    │                                 ├── rechazar con nota en el tablero (S) ──► [pendiente]
     │    │                                 └── cancelar con orq tarea (S) ──► [cancelada]
     │    ├── ok, sin gate (O) ──► [hecha]
     │    └── error sin intentos · violación · seguridad (O) ──► [fallida] ── reintentar (C o S) ──► [pendiente]
     └── cancelar (C o S lo pide; O termina el proceso) ──► [cancelada]

   pendiente | bloqueada | fallida ── cancelar (C o S) ──► [cancelada]
   [hecha] y [cancelada] son terminales.
```

| Transición | Quién | Condición |
|---|---|---|
| (nueva) → pendiente/bloqueada | O | solicitud válida de C; bloqueada si tiene deps abiertas |
| bloqueada ↔ pendiente | O | deps cumplidas, o edición de C que agrega una dep abierta. **[E2]** también sin agente apto (garantía mínima o revisor distinto) |
| pendiente → en_curso | O | cupo global y por agente, cambio libre (ninguna tarea del cambio en `en_curso` ni en `esperando_gate`), agente disponible, `no_antes_de` vencido |
| en_curso → pendiente | O | límite de plan (no suma intento), interrupción (suma `interrupciones`), error con intentos disponibles |
| en_curso → esperando_gate / hecha | O | terminó ok: con gate → esperando_gate; sin gate → hecha. **[E3]** además con la respuesta válida, y esperando_gate si alguna prueba esperada no pasó |
| en_curso → fallida | O | error sin intentos, `violacion`, `seguridad`, 7 límites de plan o más de 2 interrupciones. **[E3]** también `formato_respuesta` y `contrato` |
| esperando_gate → hecha / pendiente | S (tablero) | aprobar / rechazar con nota, con la huella vigente y el código de la terminal (sección 5) |
| no terminal → cancelada | C o S (`orq tarea`) | si estaba en curso, O termina el proceso |
| fallida → pendiente | C o S (`orq tarea`) | reintentar (`max_intentos` = `intentos` + 1) |

## 5. Gates por botón en el tablero [E1]

Sebastian decide cada gate en el detalle de la tarea, con **Aprobar** o **Rechazar con nota**. Es la única
acción del tablero que cambia el estado.

**Flujo:**
1. El detalle de una tarea en `esperando_gate` muestra:
   - El `diff --stat`, incluidos los archivos nuevos sin seguimiento.
   - El informe del agente (`resultados\<id>.md`).
   - La **huella del estado**: los primeros 12 caracteres de un SHA-256.
2. Sebastian pulsa Aprobar o Rechazar. El navegador manda `POST /api/gate/<p>/<id>/preparar` con la huella que se
   está mostrando.
3. El servidor:
   - Comprueba la sesión, la protección CSRF y el origen.
   - Recalcula la huella. Si no coincide con la enviada, responde 409: "el estado cambió, vuelve a revisar".
   - Imprime **solo en la terminal** donde corre `orq correr`:
     `Código para APROBAR T-7 (huella 3fa9c1d2e4b5): 483 921 — vence en 120 s`.
4. Sebastian escribe ese código de 6 dígitos en el tablero y confirma. Va en
   `POST /api/gate/<p>/<id>/confirmar`, con la huella, el código y la nota si es un rechazo.
5. El servidor valida el código (un solo uso, 120 s) y vuelve a comparar la huella. Después pone la decisión en la
   cola del bucle. El bucle la aplica y escribe el historial: `por: sebastian`, `via: tablero`, la huella, la
   sesión y la hora. También emite un evento `gate` e imprime una línea de confirmación en la terminal.

**Huella del estado.** Es el SHA-256 de:
- El id de la tarea y el número de intento.
- El HEAD del worktree.
- `git diff --binary HEAD` (cambios en archivos con seguimiento).
- La lista de archivos sin seguimiento no ignorados, cada uno con su propio SHA-256.
- El SHA-256 de `resultados\<id>.md`.

Mientras una tarea está en `esperando_gate`, ninguna otra tarea de su cambio arranca. Así lo revisado no cambia
debajo de Sebastian.

**Mitigaciones contra un agente que apruebe en nombre de Sebastian:**

| Mitigación propuesta | Decisión | Por qué / qué cubre | Qué no cubre |
|---|---|---|---|
| Token de sesión que solo se imprime en la terminal, sin disco | **Elegida, reforzada**: la terminal muestra un **enlace de entrada de un solo uso**; al usarlo se canjea por una cookie de sesión aleatoria que vive solo en la memoria del proceso. Se elimina `tablero.token` | Un agente ya no puede leer un archivo con el token. El enlace que queda en el historial del navegador ya no sirve | Un proceso del mismo usuario puede leer el buffer de la consola (`AttachConsole`), la memoria del orquestador (`ReadProcessMemory`) o la cookie del navegador (cifrada con DPAPI del mismo usuario) |
| Escucha solo en 127.0.0.1 | **Elegida** (ya estaba) | Nada desde otra máquina | Cualquier proceso local |
| Comprobación de Origin y protección CSRF | **Elegida**: cookie `SameSite=Strict`, token CSRF por sesión en una cabecera, `Origin` y `Host` propios obligatorios, `Content-Type: application/json` | Páginas web maliciosas, CSRF y rebinding de DNS | Un proceso local que ya tenga la sesión fija las cabeceras que quiera |
| Aprobar un estado concreto (huella del diff y del informe mostrados) | **Elegida** | Que se apruebe algo distinto de lo que Sebastian vio (cambios después de revisar, un informe reemplazado) | No impide aprobar el estado actual si el atacante tiene sesión y código |
| Registro de quién y cuándo, más confirmación en dos pasos | **Elegida, con el segundo paso atado a un código que solo aparece en la terminal**, nunca en HTTP ni en disco. Además, 3 códigos erróneos bloquean los gates hasta reiniciar | El código obliga a leer la terminal en ese momento. El registro y la línea en la terminal dejan rastro visible | Un proceso que lea la consola en ese momento obtiene el código |
| Reglas deny para que los agentes no lean ni escriban la carpeta de estado ni se conecten al puerto | **Elegida como defensa en profundidad**: `Read`/`Edit` denegados sobre la raíz de estado y la carpeta de Cowork; `curl`, `wget`, `Invoke-WebRequest` e `Invoke-RestMethod` denegados en `Bash(...)` y `PowerShell(...)`; WebFetch fuera de `--tools` salvo con red | Lo directo y accidental | En `cc` sobre Windows es **Instrucción**: `python -c "urllib.request.urlopen('http://127.0.0.1:8765/…')"` lo rodea |
| Canal de decisiones en memoria (tablero dentro del orquestador) | **Agregada por mí, elegida** | Antes bastaba con que un agente escribiera un archivo en `decisiones\` para aprobar un gate. Ahora ese archivo no existe para los gates y el bucle rechaza cualquier archivo que lo intente | — |
| Aviso de integridad del código del orquestador | **Agregada por mí, elegida**: si el árbol de la instalación tiene cambios sin commit al iniciar, el tablero lo avisa y los gates quedan deshabilitados salvo con `--permitir-codigo-modificado` | Un agente que modificó el código del orquestador para aprobarse a sí mismo | Un agente que además haga commit en el repo del orquestador, o que modifique el intérprete de Python |
| Confirmación en el escritorio seguro de Windows (pedir la contraseña) | **Descartada en E1** | Sería la única barrera fuera del alcance de un proceso del mismo usuario | Exige manejar la credencial de Sebastian y llamar a `credui` y `LogonUser` con `ctypes`. Es complejo y delicado. Queda para estudiar junto con la decisión 6 |
| Puerto aleatorio en cada arranque | **Descartada** | — | Recorrer los puertos de localhost es trivial, y se pierden los marcadores |
| Nonce de un solo uso devuelto por HTTP como segundo paso | **Descartada** | — | Un proceso con sesión lo obtiene en la misma respuesta: automatizarlo es trivial |

**Lo que no queda cubierto** (con `cc` en Windows nativo, que corre con el mismo usuario y sin sandbox):
- Un agente decidido puede, por medio de un intérprete:
  - Leer la memoria del proceso del orquestador: token, sesión y código vigente.
  - Leer el buffer de la consola.
  - Leer o descifrar las cookies del navegador.
  - Leer el portapapeles y capturar la pantalla.
  - Mandar pulsaciones o automatizar la ventana del navegador.
  - Matar el orquestador y lanzar otro modificado.
  - Editar `tareas.json` mientras el orquestador está detenido.
  - Cambiar el código del orquestador y hacerle commit.
- Las defensas suben el costo y dejan rastro (historial, eventos, líneas en la terminal, aviso de integridad),
  pero no lo impiden.
- La barrera de fondo sigue siendo que **ningún gate publica código**: el commit lo hace Sebastian a mano.
- La solución real es correr los agentes con otra cuenta de Windows (decisión 6).
- En **[E2]**, `codex` con sandbox `elevated` no puede escribir fuera del worktree y no tiene red. Si además le
  impide abrir la memoria de otros procesos no está verificado.

## 6. Adaptadores [E1 cc, E2 codex, E4 cursor]

Interfaz (`adaptadores/base.py`):

```python
class Adaptador(Protocol):
    nombre: str                                    # "cc" | "codex" | "cursor"
    version_minima: str
    banderas_prohibidas: tuple[str, ...]
    def lanzamiento(self, t: Tarea, ctx: Contexto) -> Lanzamiento   # argv, env, cwd, stdin, archivos a escribir
    def normalizar(self, linea: dict, estado: EstadoLectura) -> list[Evento]
    def limite(self, estado: EstadoLectura, codigo: int, stderr: str) -> Limite | None
    def cierre(self, estado: EstadoLectura, codigo: int, stderr: str) -> Resultado
```

| | **cc** [E1] (Claude Code 2.1.306) | **codex** [E2] (Codex CLI 0.163.0) | **cursor** [E4] (Cursor CLI 2026.10.08) |
|---|---|---|---|
| Ejecutable | ruta absoluta en config (p. ej. `%USERPROFILE%\.local\bin\claude.exe`) | `%LOCALAPPDATA%\OpenAI\Codex\bin\<hash>\codex.exe`: se busca el patrón y se elige la carpeta con la **versión más alta** según `--version` (si empatan, la más reciente por fecha). Se puede fijar una ruta absoluta en config | `%LOCALAPPDATA%\cursor-agent\agent.ps1`, un script de PowerShell. Se lanza con `%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -NonInteractive -File <agent.ps1>`, o con el binario real que envuelva el script si se encuentra (por verificar). Nunca texto libre en argumentos de PowerShell: el prompt va por archivo |
| Lanzar sin ventana | `-p --output-format stream-json --verbose --permission-mode dontAsk --permission-prompts none --restricted --tools <lista> --settings <perfil.json> --strict-mcp-config --session-id <uuid>`; prompt por stdin | `exec --json --cd <wt> --ignore-user-config --sandbox workspace-write -c approval_policy="never" -c sandbox_workspace_write.network_access=false -c windows.sandbox="elevated" -c shell_environment_policy.ignore_default_excludes=false -`; prompt por stdin | `-p --output-format stream-json --workspace <wt> --trust "<puntero al archivo de prompt>"`; `CURSOR_CONFIG_DIR=<perfil>`, `NO_OPEN_BROWSER=1`; stdin cerrado |
| Retomar sesión | `--resume <uuid>` (el uuid lo genera el orquestador) | mismas opciones y `resume <thread_id> -`; el id sale de `thread.started` | `--resume <session_id>` de `system/init` (que sea el `chatId` está por verificar) |
| Eventos | NDJSON: `system/init`, `assistant`, `user`, `rate_limit_event`, `system/api_retry`, `result` | JSONL: `thread.started`, `turn.*`, `item.*` (agent_message, command_execution, file_change, mcp_tool_call, web_search, todo_list, error), `error` | NDJSON: `system/init`, `user`, `assistant`, `tool_call` started/completed, `result` |
| Límite del plan | `rate_limit_event` con `status: "rejected"` (`resetsAt`), `assistant.error == "rate_limit"`, o los textos "hit your … limit", "usage limit", "limit · resets" | "hit your usage limit" en `error` o `turn.failed` (normalizando ’→'); la hora sale de "Try again at <hora>" | no documentado: salida ≠ 0 sin `result` y "usage limit" en stderr o en el texto; reintento a 30 min |
| Consumo | `result.usage` y `total_cost_usd` (estimado) | suma de `turn.completed.usage`; sin costo | sin tokens ni costo; solo `duration_ms` |
| Resultado | `result.result`, `is_error`, `subtype`, `permission_denials` | último `agent_message`; salida 1 si el turno falló | `result.result`, `is_error`; puede terminar sin `result` |
| Modo lectura [E2] | `--tools "Read,Glob,Grep,Bash,TodoWrite"` + `Edit` negado | `--sandbox read-only` | `--mode ask` + `Write(**)` negado (por verificar) |

Notas:
- **cc**:
  - Perfil (`--settings`): `permissions.allow` y `deny` como en el v0, más las reglas `PowerShell(...)`
    equivalentes, `disableBypassPermissionsMode: "disable"` y `disableAllHooks: true`.
  - Entorno: sin `ANTHROPIC_API_KEY` y con `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` y `DISABLE_AUTOUPDATER=1`.
  - Si `--restricted` no funciona con OAuth de suscripción (decisión 7), se usa el respaldo
    `--setting-sources user` con el mismo `--settings`.
- **codex** [E2]:
  - `-a` no existe en `exec`; la aprobación se fija con `-c approval_policy`.
  - `--ignore-user-config` deja fuera `config.toml` pero conserva la autenticación de `CODEX_HOME`.
  - El worktree nunca se marca como confiable.
  - `windows.sandbox` va explícito para que falle cerrado (decisión 9).
- **cursor** [E4]:
  - Sin `--force`, `--yolo`, `--approve-mcps`, `--sandbox disabled`, `--auto-review` ni `-w`.
  - `--trust` es obligatorio sin ventana pero activa los hooks del repo; por eso existe la revisión de huellas.
  - Viene `habilitado: false` hasta la verificación manual (decisión 8).
  - Si el lanzador necesita `-ExecutionPolicy Bypass`: es la política de scripts de PowerShell, no un bypass de
    permisos del agente. La lista de banderas prohibidas de cursor debe permitirlo solo en la posición del
    lanzador. Por verificar: el changelog dice que funciona con políticas restringidas.
- **Prompt por argumento**: con `.cmd`, `.bat` o `.ps1`, el texto libre en argumentos permite inyectar comandos
  (clase "BatBadBut"). El prompt va a `<wt>\.orq\prompt-<id>-<n>.md`, excluido de git y borrado al terminar.
- **Versión mínima**: 2.1.302 (cc), 0.163.0 (codex) y 2026.10.08 (cursor). Una versión menor deja el agente no
  disponible; una mayor se marca "no verificada".
- **[E3] Paridad**: se suman `--plugin-dir`, `Skill`, `--mcp-config`, `--model` y `--effort` en cc;
  `-c mcp_servers.*`, `-m`, `-c model_reasoning_effort` y `-c project_doc_max_bytes` en codex; el slug de
  `--model` en cursor.

## 7. Seguridad por agente [E1 cc, E2 codex, E4 cursor]

Niveles:
- **Duro**: no hay forma de saltárselo con los permisos dados.
- **Sandbox**: lo impone el sistema operativo vía el sandbox del agente.
- **Instrucción**: depende del modelo, o de una regla que se rodea con un intérprete permitido.

Tabla para Windows 11 nativo:

| Control | cc | codex (`elevated` o `mxc`) | cursor |
|---|---|---|---|
| 1. Sin bypass de permisos | Duro | Duro | Duro en banderas; Instrucción en config hasta verificar `CURSOR_CONFIG_DIR` |
| 2. Sin git commit, push, reset ni checkout | Instrucción (+ detección) | Sandbox | Instrucción (+ detección) |
| 3. Sin lectura de credenciales | Instrucción (env: Duro) | Instrucción al leer; Sandbox para sacarlas por red (env: Duro) | Instrucción (env: Duro) |
| 4. Escritura solo en el worktree | Instrucción (herramientas de archivo: Duro) | Sandbox | Instrucción |
| 5. Red solo si la tarea la pide | Instrucción (WebFetch y WebSearch: Duro) | Sandbox (más débil en `unelevated`) | Instrucción |

Cómo se cumple cada control:

1. **Sin bypass de permisos.**
   - Los tres: el orquestador revisa el comando contra las banderas prohibidas antes de lanzar.
   - cc: `dontAsk`, `--restricted` (rechaza `bypassPermissions`, no carga los settings del usuario ni del
     repo), `disableBypassPermissionsMode` en `--settings`.
   - codex: `--ignore-user-config`, worktree no confiable, aprobación `never`.
   - cursor: banderas seguras; `CURSOR_CONFIG_DIR` con perfil propio; no lanza si el `cli-config.json` del usuario
     tiene `unrestricted` o un `allow` amplio.
2. **Sin git commit, push, reset ni checkout.**
   - cc: `allow` solo con git de lectura; `dontAsk` niega el resto; `deny` repite commit, push, reset,
     checkout, switch, restore, stash, merge, rebase, clean, `branch -d` y `git -C` en `Bash(...)` y
     `PowerShell(...)`. Se rodea con un script.
   - codex: `.git` y el gitdir resuelto del worktree quedan de solo lectura; `push` falla sin red.
   - cursor: `Shell(git)` negado completo (la regla compara solo el primer token).
   - Los tres: auditoría posterior (D7.b).
3. **Sin lectura de credenciales.**
   - Los tres: entorno filtrado, worktree sin `.env` ni llaves, raíz de estado fuera de todo repo, credenciales de
     los propios agentes negadas (`~/.claude`, `~/.codex`, `~/.cursor`).
   - cc: `Read(...)` deny cubre Read y "cat, head, tail, sed, tee"; no cubre `grep -r` ni scripts.
   - codex: `workspace-write` lee todo el disco. Los perfiles de permisos con `deny` "do not compose" con
     `--sandbox`.
   - cursor: `Read(...)` solo cubre la herramienta; `.cursorignore` no frena la terminal.
   - **`~/.embudo` (WatchGuard)**: sigue en el perfil de Sebastian por decisión del 22-10-2026, así que con cc
     se puede leer con un script. Riesgo abierto (sección 19).
4. **Escritura solo en el worktree.**
   - cc: `--restricted` limita las herramientas de archivo, pero Bash no tiene sandbox en Windows.
   - codex: lo impone el sandbox.
   - cursor: `Write(...)` solo cubre la herramienta.
5. **Red solo si la tarea la pide** (con `red.permitida` en el proyecto y `red: true` en la tarea).
   - cc: WebFetch y WebSearch solo entran a `--tools` con red; `curl`, `wget`, `Invoke-WebRequest`,
     `Invoke-RestMethod`, `pip install` y `npm install` van en deny. Se rodea con Python.
   - codex: `network_access=false`.
   - cursor: `WebFetch(dominio)`.
   - En E1 esto también protege el puerto del tablero (sección 5).

**D7.a Mecanismos que se pueden saltar:**
- Hooks de git (`--no-verify`, `-c core.hooksPath=`).
- Reglas de comando de cc (`sh -c`, `env git`, alias, intérpretes).
- `Shell(cmd)` de Cursor (solo el primer token).
- `.rules` de Codex (experimentales, solo `bash -lc`, se apagan con `--ignore-rules`).
- Hooks de Cursor sin `failClosed` y hooks de Codex ("not a complete enforcement boundary").
- `.cursorignore`.
- Instrucciones en el prompt, `AGENTS.md` o `CLAUDE.md`.
- La auditoría posterior: detecta pero no previene; un agente con escritura sobre `.git` puede borrar el reflog,
  y un push a una URL directa no actualiza las refs de seguimiento.

**D7.b Capas del orquestador, iguales para todos:**
1. Revisión de banderas prohibidas.
2. Perfil generado por corrida.
3. Entorno filtrado.
4. Worktree sin secretos y huellas aprobadas de la config de agentes del repo.
5. Matriz de garantías y, **[E2]**, `garantia_minima` que falla cerrado.
6. Auditoría de git antes y después (HEAD, refs, reflog, stash, worktrees, huellas de `.git/config` y
   `.git/hooks`, con `GIT_OPTIONAL_LOCKS=0`).
7. Job Object.
8. Raíz de estado y carpeta de Cowork negadas en cada perfil.
9. **[E1]** Gates por botón con las mitigaciones de la sección 5.

## 8. Eventos [E1 esquema y cc; E2 y E4 su normalización]

```json
{"v": 1, "ts": "2026-10-21T16:40:00-03:00", "proyecto": "demo", "tarea": "T-12", "intento": 2,
 "agente": "cc", "seq": 41, "tipo": "comando",
 "datos": {"comando": "py -3.12 -m unittest", "estado": "ok", "codigo_salida": 0}}
```

| Normalizado | cc [E1] | codex [E2] | cursor [E4] |
|---|---|---|---|
| `inicio` | `system/init` (session_id, model) | `thread.started`; el modelo sale del perfil | `system/init` |
| `mensaje` | bloque `text` de `assistant` | `item.completed` agent_message | `assistant` sin `model_call_id` |
| `herramienta` | Read/Glob/Grep/WebFetch/WebSearch/TodoWrite/mcp__* | web_search, mcp_tool_call, todo_list | readToolCall o `function` |
| `archivo` | Edit/Write/MultiEdit/NotebookEdit sin error | file_change, uno por cambio | writeToolCall o editToolCall (por verificar) |
| `comando` | Bash/PowerShell en_curso y ok/error | command_execution (`declined` → `negado`) | shellToolCall (por verificar) |
| `fin` / `error` | `result`; `is_error`, `rate_limit_event` | `turn.completed` / `turn.failed`, `error` | `result`; salida ≠ 0 sin `result` |
| se ignora | thinking y parciales | reasoning, `item.updated` | thinking |

Reglas de escritura:
- Lista blanca de campos. Nunca se copian `tool_result.content`, `aggregated_output`, `fileText` ni los
  argumentos completos de MCP.
- Rutas relativas al worktree, con `~` en vez del home.
- Redacción de secretos (`sk-ant-…`, `sk-…`, `ghp_…`, `github_pat_…`, `AKIA…`, `xox[abpr]-…`, PEM,
  `Authorization`/`Bearer`, `password=`/`token=`/`api_key=`, JWT y los patrones extra del proyecto).
- 4 KB por línea y 2.000 eventos de detalle por intento.
- Rotación a 10 MB, con 5 archivos rotados.
- Los lectores abren, leen y cierran en cada consulta.
- **[E2]** Requisito "normalización igual para los agentes": cc y codex. **[E4]** suma cursor.

## 9. Planificador y ejecución [E1; agregados E2 y E3]

- **Candidatas**: `pendiente`, `no_antes_de` vencido, agente disponible y no agotado, y cambio libre (ninguna
  tarea del cambio en `en_curso` ni en `esperando_gate`). Se ordenan por prioridad y fecha de creación. El cupo
  global y por agente suma todos los proyectos.
- **Preparar la corrida**:
  1. Worktree, bajo un candado por repo.
  2. Revisiones de seguridad.
  3. Foto de git.
  4. Perfil del agente.
  5. `Popen` con la ruta absoluta del ejecutable, `CREATE_NO_WINDOW`, pipes y stdin.
  6. Job Object con `KILL_ON_JOB_CLOSE`. El orquestador también va en un Job propio; `taskkill /T /F` es el
     respaldo.
- **Al terminar**: foto y auditoría de git, `diffstat` (incluidos los archivos nuevos), resultado y salida de
  Cowork.
- **Límite del plan**: la tarea vuelve a `pendiente` sin sumar intento, `agotado_hasta` queda por agente y al
  séptimo límite pasa a `fallida`.
- **Prompt**: encabezado fijo del orquestador, el prompt de la tarea y avisos (rechazo con nota, interrupción,
  traspaso). **[E3]** lo reemplaza el paquete del contrato.
- **[E2]** Traspaso (decisión 1, aceptada) y revisión por un agente distinto en modo lectura (decisión 2,
  aceptada).
- **[E3]** Elegibilidad por capacidades y validación de la respuesta.
- **Concurrencia**: límite global de 2 por defecto.

## 10. Tablero [E1; vista de paridad en E3]

- **Servidor**: `ThreadingHTTPServer(("127.0.0.1", puerto))` en un hilo de `orq correr`. La dirección está fija
  en el código.
- **Páginas**:
  - `/`: kanban por estado con filtros por proyecto y agente.
  - `/tarea/<p>/<id>`: campos, historial, actividad en vivo (polling cada 1,5 s desde `seq`), resultado,
    consumo, `diffstat`, niveles de garantía y, en `esperando_gate`, la huella y los botones (sección 5).
  - `/consumo`.
  - **[E3]** `/paridad`.
- **Estáticos** propios, sin CDN.
- **Protección**:
  - Enlace de entrada de un solo uso impreso en la terminal y cookie de sesión en memoria (`HttpOnly`,
    `SameSite=Strict`).
  - Validación de `Host` y `Origin`.
  - CSP `default-src 'self'` y `X-Frame-Options: DENY`.
  - `GET` y `HEAD` para todo; `POST` solo en las dos rutas del gate.
- **Solo lectura salvo el gate**: el tablero no escribe archivos. La única escritura es la decisión de gate, que
  pasa al bucle por la cola en memoria. El `diff --stat` lo calcula el orquestador, no el tablero.

## 11. Lectura del estado por Cowork [E1]

- **Carpeta que se conecta en la app de Cowork**: `%USERPROFILE%\Orquestador-Cowork\<proyecto>\`, o
  `Orquestador-Cowork` entera para ver todos los proyectos.
  - Queda **fuera** de la raíz de estado. Conectarla no expone `tareas.json`, `sesiones.json`, `corridas\`,
    `config.json`, los eventos completos ni la configuración de los agentes.
  - El orquestador se niega a arrancar si `cowork_raiz` está dentro de la raíz de estado o de un repo, o al
    revés.
- **Contenido**:
  - `entrada\`: lo escribe Cowork.
  - `respuestas\`: acuses.
  - `salida\`: solo lectura para Cowork; el orquestador la reescribe.
- **`salida\`** (escritura atómica, como máximo cada 2 s después de un cambio):
  - `estado.json` (`v`, `generado_en`, `orquestador` {vivo, latido}, `agentes` {disponible, versión,
    agotado_hasta}, `tareas`). Cada tarea trae:
    - id, título, estado, motivo, agente, cambio, rama y dependencias;
    - gate: requiere, decisión, nota, en y la huella corta;
    - intentos, interrupciones, `no_antes_de`;
    - resultado: ok, resumen, clase y mensaje del error, ya redactados;
    - consumo, marcas de tiempo y las últimas 20 entradas del historial.

    Sin el prompt completo, que Cowork ya tiene; solo su hash.
  - `eventos-recientes.json`: los últimos 300 eventos normalizados (los mismos de la lista blanca, redactados),
    con textos truncados a 500 caracteres.
  - `consumo.json`: totales por agente y por día.
  - `resultados\<id>.md`: texto final de cada tarea, redactado.
  - `diffstat\<id>.json`: archivos y líneas, sin contenido.
- **Sin secretos ni datos**:
  - Todo sale de campos de lista blanca y pasa por la redacción.
  - No se incluyen stderr, salidas de comandos, contenido de archivos, rutas absolutas fuera del worktree, tokens
    ni la configuración.
  - Una prueba siembra secretos sintéticos en el entorno, el prompt, stderr y los eventos, y verifica que no
    aparecen en `salida\`.
- **El orquestador nunca lee `salida\`.** Si Cowork la modifica, se reescribe en el siguiente ciclo.
- **Agentes**: la carpeta de Cowork queda negada (lectura y escritura) en cada perfil, para que no puedan crear
  solicitudes.

## 12. Compatibilidad v0 [E1]

- `puente.py` no cambia y gana pruebas de regresión con el falso de cc.
- La entrada del v1 convierte los trabajos v0 de `tipo: cc` (sin `op`, con `tipo`). Los de `tipo: git` o con
  `repo` se rechazan.
- `orq importar-v0` solo lee el origen y por defecto simula. No se corre contra la carpeta de Embudo en E1.

## 13. Pruebas [E1 base; cada etapa suma las suyas]

- `unittest` de la librería estándar: `py -3.12 -m unittest discover -s pruebas`.
- **Falso único**: `pruebas/falsos/agente_falso.py --como cc` en E1; `codex` en E2 y `cursor` en E4.
  - Lee guiones de `pruebas/guiones/`. En E1: `ok`, `lectura`, `limite`, `error`, `colgado`, `hijo_largo`,
    `sesion_inexistente` e `intenta_commit`.
  - **[E3]** suma `respuesta_sin_bloque`, `respuesta_incompleta`, `prueba_fallida` y `toca_no_tocar`.
  - Deja una traza con argv, stdin, carpeta de trabajo, `PATH`, `VIRTUAL_ENV`, los nombres (no los valores) de
    las demás variables y, **[E3]**, las skills y los MCP que ve.
- **Ejecutable falso por ruta absoluta**: en las pruebas, la config apunta `agentes.cc.ejecutable` al
  `python.exe` del intérprete de pruebas con el script como argumento. Así se prueba que no se usa el `PATH`.
- Repos sintéticos con `git init` en carpetas temporales. La red se bloquea salvo loopback.
- **Pruebas del gate**:
  - Sin sesión → 401. Sin CSRF u `Origin` → 403.
  - Huella vieja → 409. Código erróneo 3 veces → bloqueo.
  - El código nunca aparece en respuestas HTTP ni en disco: se revisa toda la raíz y el directorio temporal
    después del flujo.
  - Un archivo de gate dejado en `decisiones\` se rechaza.

## 14. Paridad de capacidades [E3; cursor en E4]

Regla general:
- **Lo común va en el paquete de entrada**, idéntico byte a byte para todos los agentes.
- **Lo nativo se genera desde una sola fuente** en la ruta que cada agente lee.
- La matriz de capacidades (`capacidades.py`, con la fuente de cada celda) decide qué agente es elegible. Lo que
  no está verificado se trata como "no puede" (decisión 18, aceptada).

### 14.1 Instrucciones (decisión 12, aceptada)

| | Qué lee sin ventana | Fuente |
|---|---|---|
| cc | `CLAUDE.md`, `.claude/CLAUDE.md` y `CLAUDE.local.md` desde la carpeta de trabajo hacia arriba, `.claude/rules/*.md`, `~/.claude/CLAUDE.md` y la política gestionada. Lee `AGENTS.md` de forma nativa desde 2.1.277 **solo si no hay ningún `CLAUDE.md` ni `CLAUDE.local.md`**. `@ruta` se expande ("expanded and loaded into context at launch"), hasta 4 saltos. Tope de 4 MiB | code.claude.com/docs/en/memory, …/headless, …/env-vars |
| codex | `AGENTS.override.md` o `AGENTS.md` global en `CODEX_HOME`; en el proyecto, uno por carpeta desde la raíz de git hasta el cwd (incluye `project_doc_fallback_filenames`). **Tope total de 32 KiB, global incluido, que trunca**. Solo se bloquea si el proyecto está marcado `untrusted` | learn.chatgpt.com/docs/agent-configuration/agents-md; codex-rs/core/src/agents_md.rs |
| cursor | `AGENTS.md` de la raíz y anidados; `CLAUDE.md` de la raíz, siempre aplicado; `.cursor/rules/*.mdc`; reglas de equipo y de usuario. **`@archivo` no se expande** | cursor.com/docs/cli/using, cursor.com/docs/rules |

- **Fuente única**: `AGENTS.md`, y `CLAUDE.md` con solo `@AGENTS.md`.
  - Cursor no expande `@`, así que no duplica contenido.
  - Codex recibe `-c project_doc_max_bytes=65536` para que un `AGENTS.md` global no trunque el del proyecto.
  - Se rechazan: enlaces simbólicos (en Windows git usa `core.symlinks=false`), copias generadas (se
    desincronizan y Cursor duplicaría) y un "lee AGENTS.md" (depende del modelo).
- **Revisiones**: `AGENTS.md` mide 32 KiB o menos, el `CLAUDE.md` no trae contenido propio y se avisa de los
  archivos anidados y de las instrucciones personales de cada agente.

### 14.2 Skills (decisión 13, aceptada)

| | Rutas | Sin ventana | Frontmatter | Fuente |
|---|---|---|---|---|
| cc | `.claude/skills` (proyecto y padres), `~/.claude/skills`, plugins (`--plugin-dir`), `--add-dir`. **No lee `.agents/skills`** | sí; herramienta `Skill` en `--tools` (inferido para el CLI); con `--restricted`: sin verificar | estándar + extensiones; **`allowed-tools` concede permisos y `hooks` registra hooks, incluso en `-p` sin confianza** | code.claude.com/docs/en/skills |
| codex | `.agents/skills` del cwd a la raíz, `~/.agents/skills`, `/etc/codex/skills`, sistema; en el código, también `.codex/skills` | sin verificar (no hay exclusión en el código) | `name`, `description`, `metadata.short-description` | learn.chatgpt.com/docs/build-skills; codex-rs/ext/skills |
| cursor | `.agents/skills`, `.cursor/skills`, `.claude/skills`, `.codex/skills` y sus equivalentes de usuario | sí, desde 7-may-2026 | `name`, `description`, `paths`, `disable-model-invocation`, `user-invocable`, `metadata` | cursor.com/docs/skills |

- **Estándar** (agentskills.io/specification): `name` de 1 a 64 caracteres `a-z0-9-`, igual a la carpeta;
  `description` de 1 a 1.024 caracteres. Opcionales: `license`, `compatibility`, `metadata` y `allowed-tools`
  (experimental). Convención entre clientes: `.agents/skills`.
- **Campos portables**: `name`, `description`, `license`, `compatibility` y `metadata`.
- **Publicación**:
  - Fuente: `.agents/skills/` del proyecto + `skills.fuentes_extra` + globales `orq-<n>` en `<instalación>/skills/`.
  - cc: un plugin `orq` generado fuera del worktree, que se pasa con `--plugin-dir`. Respaldo: copias en
    `.claude/skills`.
  - Globales: se materializan en `.agents/skills/orq-<n>`.
  - codex y cursor: leen `.agents/skills`. Las fuentes extra se copian a `.agents/skills`; esa es la única
    repetición conocida, en Cursor.
  - Las copias llevan el marcador `.orq-generado` y quedan en un bloque de `.git/info/exclude`.
- **Paquete**: el índice de skills y las skills pedidas completas van en el paquete para todos.

### 14.3 MCP

- **Declaración**: lista blanca `mcp_permitidos` en `config.json` (comando con versión fija, nombres de
  variables permitidas, `red`, herramientas). El proyecto habilita un subconjunto y la tarea elige.
- **cc**: `--mcp-config` + `--strict-mcp-config`, y `mcp__srv__*` en allow.
- **codex**: `-c mcp_servers.<id>.{command,args,env,enabled_tools,required}` y `tools.<t>.approval_mode="approve"`
  (con `never`, lo que pide aprobación se niega). Junto con `--ignore-user-config`: sin verificar.
- **cursor**:
  - `.cursor/mcp.json` generado + `agent mcp enable`. No anula `~/.cursor/mcp.json`.
  - Sin ventana: sin verificar; el foro reporta errores. **No elegible para MCP** hasta la verificación, y no se
    lanza si el `mcp.json` del usuario no está vacío.
- Los servidores MCP corren fuera del sandbox (documentado en cc; se asume en los otros dos).

### 14.4 Entorno (decisiones 15 y 16, aceptadas)

- **Carpeta de trabajo**: el worktree para todos.
- **Venv**: compartido del proyecto (`<repo>\.venv` por defecto) y de solo lectura para los agentes; `pip
  install` está negado.
- **Variables**: el `PATH` lo calcula el orquestador (`<venv>\Scripts`, `path_extra`, `PATH` del sistema
  filtrado), junto con `VIRTUAL_ENV`, `PYTHONUTF8` y `PYTHONIOENCODING`. Las variables propias de cada adaptador
  van en una lista fija. Se quita `CLAUDE_CODE_EFFORT_LEVEL`.
- **Shell**: cc usa Git Bash, codex PowerShell (pwsh, powershell, cmd) y cursor PowerShell ([foro]). Por eso los
  comandos del contrato deben ser neutros respecto del shell.

### 14.5 Contrato y respuesta (decisión 14, aceptada)

- **`contrato`**:
  - Obligatorios: `objetivo` y `criterios_aceptacion`.
  - Opcionales: `contexto`, `archivos`, `pruebas_esperadas`, `no_tocar`, `skills` y `respuesta` (`v1`, o `libre`
    para trabajos v0).
- **Paquete Markdown**, idéntico para todos y con un tope de 64 KiB. Lleva, en este orden:
  1. Reglas del orquestador.
  2. Objetivo, contexto, archivos, criterios, pruebas esperadas y lo que no se toca.
  3. Índice de skills y las skills pedidas.
  4. Formato de respuesta.
  5. Avisos.
- **Bloque final `orq-respuesta`**: `{"resumen", "pruebas": [{"comando", "resultado": "paso|fallo|no_corrida",
  "detalle"}], "tareas_abiertas", "permisos_negados": [{"accion", "texto"}]}`.
- **Validación** con librería estándar:
  - Si falla: `fallida` con clase `formato_respuesta`.
  - Si una prueba esperada no pasó: `esperando_gate`.
  - Si el diff toca `no_tocar`: `fallida` con clase `contrato`.
- **Salida estructurada nativa**: no se usa en v1.

### 14.6 Modelo, esfuerzo, sesión y shell

| | Modelo | Esfuerzo | Modelo efectivo | Sesión (doctor) | Shell |
|---|---|---|---|---|---|
| cc | `--model` (alias `default`, `best`, `fable`, `opus`, `sonnet`, `haiku`…) | `--effort low\|medium\|high\|xhigh\|max` (`--help` local; la doc agrega `ultracode`) | `system/init.model` y `.effort` | `claude auth status`, código 0/1 (doc) | Git Bash |
| codex | `-m` | `-c model_reasoning_effort=`; un valor desconocido pasa como `Custom` sin error, así que valida el orquestador | no informado con `--json`, salvo reenrutamiento | `codex login status`, código 0/1 (código) | PowerShell |
| cursor | `--model <slug>` | sin flag; va en el slug | `system/init.model` (pedido o resuelto, sin verificar) | `agent status`: códigos sin documentar, "desconocida" | PowerShell ([foro]) |

### 14.7 `doctor` (decisión 17, aceptada)

- `orq doctor [--vivo]` deja `doctor.json` y una tabla, que también se muestra en `/paridad`.
- **Columnas**:
  - Versión.
  - Sesión, solo por el código de salida, con la salida a `DEVNULL`.
  - Instrucciones, skills y MCP vistos por la vía nativa de cada agente.
  - Herramientas.
- **Credenciales**: nunca abre los archivos de credenciales de los agentes; se prueba con `sys.addaudithook`.
- **`--vivo`**: opcional, gasta plan.

### 14.8 Calibración (decisión 11, aceptada)

- `orq calibrar`: tres tareas sintéticas por agente (corregir un error con su prueba, una edición de
  documentación y una revisión en modo lectura).
- Compara formato, pruebas, diff, consumo, negaciones y modelo efectivo.
- Se corre al habilitar un agente, al cambiar su versión y antes de activar el traspaso automático hacia él.
- No es requisito para arrancar.
- Entra en E3, junto con `doctor`, y se amplía en E4.

## 15. Rutas de ejecutables por etapa

| Etapa | Agente | Ruta | Cómo se resuelve |
|---|---|---|---|
| E1 | cc | ruta absoluta en `config.json` (en este PC, `which` mostró `%USERPROFILE%\.local\bin\claude`) | se usa tal cual; no se busca en el `PATH` |
| E1 | git | ruta absoluta en `config.json` | igual |
| E2 | codex | `%LOCALAPPDATA%\OpenAI\Codex\bin\<hash>\codex.exe` | patrón `bin\*\codex.exe`; se elige la versión más alta según `--version` (con empate, la más reciente por fecha) y se registra en `agentes.json`; se reevalúa al iniciar. Una ruta absoluta en config tiene prioridad |
| E4 | cursor | `%LOCALAPPDATA%\cursor-agent\agent.ps1` | por medio de `powershell.exe -NoProfile -NonInteractive -File`, o del binario real que envuelve si se encuentra. Prompt por archivo, nunca en argumentos |

## 16. Plan de migración

1. **E1** en este repo sin tocar `puente.py`; las pruebas de regresión del v0 entran primero.
2. Sebastian crea una raíz de estado de prueba y un proyecto sintético, conecta en Cowork solo su carpeta de
   `Orquestador-Cowork` y corre la verificación manual de cc (`docs/verificacion-manual.md`).
3. **E2 a E4** según `docs/etapas.md`.
4. Embudo sigue con su v0 hasta un change aparte.
5. **Vuelta atrás**: detener `orq correr` y volver a `puente.py`. La raíz de estado y la carpeta de Cowork se
   pueden borrar sin afectar ningún repo.

## 17. Flags verificados (21 y 22-10-2026)

| Agente | Versión | Cómo se obtuvo |
|---|---|---|
| Claude Code | 2.1.306 | `claude --version` y `claude --help` locales |
| Codex CLI | 0.163.0 (15-10-2026) | github.com/openai/codex/releases/tag/rust-v0.163.0 y npm; `codex --help`: `command not found` |
| Cursor CLI | 2026.10.08 | cursor.com/docs/cli/changelog; `agent --help`: `command not found` |

**cc**:
- Del `claude --help` local: `-p`, `--output-format text|json|stream-json`, `--verbose`, `--permission-mode`
  (acceptEdits, auto, bypassPermissions, manual, dontAsk, plan), `--permission-prompts host|none`,
  `--settings`, `--setting-sources`, `--restricted`, `--tools`, `--allowedTools`, `--disallowedTools`,
  `--strict-mcp-config`, `--mcp-config`, `--session-id`, `-r/--resume`, `--fork-session`,
  `--no-session-persistence`, `--model`, `--effort`, `--json-schema`, `--plugin-dir`, `--max-budget-usd`,
  `--bare`, `--safe-mode`, `--add-dir` e `--include-partial-messages`. Prohibidos:
  `--dangerously-skip-permissions` y `--allow-dangerously-skip-permissions`.
- De la documentación (code.claude.com/docs/en/…):
  - headless (stream-json, hooks del repo en `-p`) y agent-sdk/typescript (`result`, `rate_limit_event`).
  - permissions (deny > ask > allow, rutas `//` y `~/`, alcance de Read deny, `Bash(git push *)` no detiene
    `git -C . push`) y permission-modes (`dontAsk`; `-p` arranca en Manual desde la 2.1.302).
  - settings, sandboxing (sin sandbox en Windows), env-vars, cost-tracking, errors, memory, skills, mcp,
    model-config y cli-reference (`claude auth status`).

**codex** (código del tag rust-v0.163.0 y learn.chatgpt.com/docs/…):
- `exec`, `--json`, `-o`, `--output-schema`, `--skip-git-repo-check`, `--ephemeral`, `--ignore-user-config`,
  `--ignore-rules`, `--strict-config` y `exec resume` (exec/src/cli.rs).
- `-m`, `-p`, `-C`, `--add-dir` y `-s` (shared_options.rs). Prohibidos: `--yolo`,
  `--dangerously-bypass-approvals-and-sandbox`, `--dangerously-bypass-hook-trust` y `--approve-for-me`.
- Aprobación `Never` por defecto y stdin con `-` (exec/src/lib.rs). `-a` no existe en `exec` y `--full-auto` ya
  no se soporta.
- `.git` de solo lectura en `workspace-write` (agent-approvals-security); sandbox de Windows (windows-sandbox);
  `config-reference`.
- Límite del plan ("You’ve hit your usage limit", protocol/src/error.rs); `login status` (cli/src/login.rs);
  skills (ext/skills); MCP (mcp_tool_call.rs); shell (shell-command/src/shell_detect.rs).

**cursor** (cursor.com/docs/…):
- `-p`, `--output-format`, `--stream-partial-output`, `--model`, `--workspace`, `--resume`, `--continue`,
  `--trust`, `--sandbox`, `--mode` y `create-chat` (cli/reference/parameters). Prohibidos: `-f/--force`, `--yolo`
  y `--approve-mcps`.
- `agent` principal y `cursor-agent` alias (changelog cli-jan-08-2026).
- Eventos (output-format), permisos (permissions), `CURSOR_CONFIG_DIR` (configuration), hooks, sandbox (WSL2 en
  Windows), skills, mcp, rules y authentication.
- `--browser` y `--cloud` no existen.

## 18. Decisiones

| N.º | Tema | Estado | Recomendación / resolución |
|---|---|---|---|
| 1 | Traspaso a otro agente al agotar el plan | **Aceptada** (E2) | `traspaso: "auto"` con reglas: solo a permitidos, espera mayor a 45 min, una vez por tarea, nunca al implementador si es revisión, respetando la garantía mínima, worktree intacto, sesión nueva con aviso de traspaso, no suma intento |
| 2 | Revisión de red team con otro agente | **Aceptada** (E2) | tarea `tipo: revision` con `revisa`, en modo lectura, con agente distinto obligatorio y el gate en la revisión |
| 3 | Estructura del estado | **Aceptada**, ajustada el 22-10-2026 | raíz `%USERPROFILE%\.orquestador`; la carpeta de Cowork pasó afuera (decisión 21) |
| 4 | Tablero sin framework | **Abierta** | sin dependencias; polling cada 1,5 s |
| 5 | Reinicio con tareas en curso | **Aceptada** (E1) | vuelven a `pendiente` y retoman la sesión con aviso; más de 2 interrupciones → `fallida` |
| 6 | Aislamiento fuerte en Windows | **Abierta** | (c) preferir codex para lo sensible y apoyarse en la detección; (b) cuenta de Windows dedicada en un change siguiente. Hoy es la única forma de cerrar lo que el gate por botón no cubre y el riesgo de `~/.embudo` |
| 7 | `--restricted` en cc | **Abierta, bloquea E1** | usarlo; verificar con el binario real que acepta OAuth; si no, `--setting-sources user` con `disableAllHooks` |
| 8 | Cursor deshabilitado hasta la verificación manual | **Aceptada** (E4) | — |
| 9 | Sandbox de Codex en Windows | **Abierta, bloquea E2** | `windows.sandbox="elevated"` (`codex sandbox setup --elevated` como administrador), o `mxc` si el build cumple 26200.9278; verificar que falle cerrado |
| 10 | Canal de los gates | **Reemplazada** por la decisión de Sebastian | botón en el tablero (sección 5) |
| 11 | Calibración | **Aceptada** (E3) | `orq calibrar` opcional |
| 12 | Fuente única de instrucciones | **Aceptada** (E3) | `AGENTS.md`, y `CLAUDE.md` con `@AGENTS.md` |
| 13 | Fuente única de skills | **Aceptada** (E3) | `.agents/skills/` y `skills/` global |
| 14 | Formato de respuesta | **Aceptada** (E3) | bloque `orq-respuesta` común |
| 15 | Shell | **Aceptada** (E3) | el nativo de cada agente, con comandos neutros |
| 16 | Venv | **Aceptada** (E3) | compartido y de solo lectura |
| 17 | `doctor --vivo` | **Aceptada** (E3) | opcional y manual |
| 18 | Capacidades sin verificar | **Aceptada** (E3) | falla cerrada hasta la verificación manual |
| 19 | Tablero dentro de `orq correr` | **Abierta (nueva)** | sí: la decisión viaja en memoria y no hay archivo de gates falsificable. Costo: sin orquestador no hay tablero, y ya no es un proceso de solo lectura aislado |
| 20 | Código de confirmación en la terminal | **Abierta (nueva)** | mantenerlo: es la única parte del flujo que no pasa por HTTP. Costo: hay que tener la terminal a la vista para aprobar |
| 21 | Carpeta de Cowork fuera de la raíz de estado | **Abierta (nueva)** | `%USERPROFILE%\Orquestador-Cowork\<p>\`: conectarla en Cowork no expone el resto del estado y es difícil equivocarse de carpeta |
| 22 | Reintentar y cancelar de Sebastian | **Abierta (nueva)** | en E1 quedan en `orq tarea` (archivo en `decisiones\`, falsificable, pero de bajo impacto y visible); pasarlas al tablero con el mismo flujo del gate solo si Sebastian lo pide |
| 23 | Integridad del código del orquestador | **Abierta (nueva)** | aviso al iniciar y gates deshabilitados si la instalación tiene cambios sin commit, salvo `--permitir-codigo-modificado` |
| 24 | `~/.embudo` | **Riesgo abierto por decisión de Sebastian** | cuando se pueda, sacar las credenciales de WatchGuard del perfil de Sebastian (por ejemplo, con la cuenta dedicada de la decisión 6, o en el Administrador de credenciales de Windows con acceso solo del proceso del Embudo) |

## 19. Riesgos

- **[Mismo usuario y sin sandbox para cc (E1) y cursor (E4) en Windows]**: un agente puede leer credenciales,
  escribir fuera del worktree, usar la red y, con un intérprete, intentar aprobar un gate (sección 5). →
  Defensas en capas, matriz visible, auditoría, y el commit siempre manual. Decisión 6.
- **[`~/.embudo` legible con un script desde cc]** (riesgo aceptado el 22-10-2026) → Reglas `Read` deny (solo la
  forma directa), entorno filtrado, y que la tarea no necesite red. Si `~/.embudo` se lee, solo puede salir por la
  red o por el contexto que el agente le manda a su proveedor. Decisión 24.
- **[Un agente falsifica solicitudes de Cowork o de `orq tarea`]** → Carpeta de Cowork y raíz de estado negadas;
  esas solicitudes no pueden aprobar gates; todo queda en el historial.
- **[El código del orquestador es escribible por los agentes]** → Decisión 23 y commit manual.
- **[Flags que cambian con las actualizaciones]** → Versión mínima, "no verificada", `DISABLE_AUTOUPDATER` en cc,
  revisión del comando y verificación manual al cambiar de versión.
- **[Comportamiento de Cursor sin documentar]** → Deshabilitado, tiempo máximo, stdin cerrado, prompt por archivo.
- **[Detectar el límite del plan por texto es frágil]** → Varias señales; un límite que no se detecta gasta un
  intento, no se pierde.
- **[Windows traba archivos abiertos]** → Reintentos y lectores que abren y cierran.
- **[Inyección por argumentos con `.cmd`, `.bat` o `.ps1`]** → El prompt nunca va en argumentos.
- **[Redacción por patrones incompleta]** → Lista blanca, topes y `texto_mensajes: "nunca"`; la salida de Cowork
  usa la misma lista.
- **[Inyección de prompt desde el repo o la web]** → Red apagada por defecto, revisión por otro agente (E2),
  gates y auditoría.
- **[Paralelismo]** → Límite global de 2 y un worktree por cambio.
- **[Cowork conecta más carpetas de la cuenta]** → La carpeta de Cowork vive aparte (decisión 21) y se detectan
  las escrituras externas en `tareas.json`.
- **[E2: el sandbox `elevated` requiere administrador]** → `codex` falla cerrado mientras no esté listo.
- **[E3: instrucciones personales, skills con permisos, MCP fuera del sandbox, paquete grande, validación
  estricta, matriz desactualizada]** → Ver sección 14 y `docs/referencia/requisitos-e2-e4.md`.

## 20. Preguntas que no cambian el diseño

- Subtipos de `tool_call` de Cursor para shell y edición (E4).
- Código de salida de cc y Cursor al llegar al límite del plan (E1 y E4).
- Si el `usage` de Codex es por turno o acumulado (E2).
- Si `-c windows.sandbox="elevated"` falla cerrado sin preparación (E2).
- Si `--restricted` acepta OAuth de suscripción (E1, decisión 7).
- Qué ejecutable real envuelve `agent.ps1` (E4).
