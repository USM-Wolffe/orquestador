# Design

## Context

Ver `proposal.md` (Why).
- **Referencia completa** (todas las etapas): `docs/diseno-orquestador.md`. Etapas: `docs/etapas.md`.
- **Requisitos que salieron de este change**: `docs/referencia/requisitos-e2-e4.md`.

Estado y restricciones:
- **`puente.py` (v0)**: un trabajo a la vez con `claude -p`, permisos `dontAsk` con listas fijas, sesión por
  cambio, worktree `..\wt-<cambio>` y reencolado a 30 min cuando se agota el plan. No hay sandbox de sistema
  operativo.
- **Plataforma**: Windows 11 Pro 10.0.26200, Python 3.12, solo librería estándar. El orquestador, Claude Code y
  Cowork (en su VM, con las carpetas que Sebastian conecta) corren con el mismo usuario de Windows.
- **Claude Code**: 2.1.306 instalado. Sus flags están verificados con el `claude --help` local y la
  documentación oficial (referencia, sección 17). En Windows nativo, "Claude Code runs commands unsandboxed".
- **Decisiones de Sebastian del 22-10-2026**: E1 a E4, gate por botón, Cowork lee el estado, recomendaciones
  aceptadas y `~/.embudo` como riesgo abierto (referencia, sección 0).

## Goals / Non-Goals

**Goals:**
- Núcleo completo (registro, eventos, planificador, tablero) con un solo adaptador, `cc`, detrás de una interfaz
  que E2 y E4 reutilizan sin tocar el núcleo.
- Gate por botón con defensas reales, y una lista honesta de lo que no cubren.
- Cowork lee el estado sin ver el resto de la raíz de estado.
- Ejecutables por ruta absoluta, sin depender del `PATH`.

**Non-Goals:**
- Codex (E2), paridad y `doctor` (E3) y Cursor (E4).
- Traspaso entre agentes, revisión por otro agente y garantía mínima (E2).
- Contrato de entrada y validación del formato de respuesta (E3): en E1 la tarea lleva un `prompt` libre.
- Aislamiento con otra cuenta de Windows (decisión 6).
- Que el orquestador haga commits.

## Decisions

### D1. Un proceso con el tablero adentro

- `orq correr` es el único proceso que escribe el estado. Cada 2 s:
  1. Lee la entrada de Cowork, las solicitudes de `orq tarea` y la cola de gates.
  2. Aplica los resultados de las corridas.
  3. Recalcula los bloqueos.
  4. Lanza lo que cabe.
  5. Reescribe la salida de Cowork.
- Las corridas viven en hilos y hablan con el bucle por `queue.Queue`.
- **El tablero es un hilo del mismo proceso** (decisión 19). La decisión de un gate llega al bucle en memoria, de
  modo que no existe un archivo de gates que otro programa pueda escribir.
  - Alternativa descartada: tablero en un proceso aparte que deja la decisión en `decisiones\`. Cualquier
    proceso del mismo usuario podría escribir ese archivo.
- `orq tarea <p> <id> reintentar|cancelar`, `orq proyecto nuevo`, `orq estado` e `orq importar-v0` no escriben
  `tareas.json`.

### D2. Estado, carpeta de Cowork y ejecutables

- **Raíz de estado** `%USERPROFILE%\.orquestador\`, con `config.json`, `agentes.json`, `orquestador.lock`,
  `orquestador.json`, `registro.log` y `proyectos\<p>\`. En cada proyecto: `proyecto.json`, `tareas.json` (+
  `.bak`), `sesiones.json`, `decisiones\` (solo `orq tarea`), `eventos\`, `diffstat\` y `corridas\`.
- **Carpeta de Cowork** `%USERPROFILE%\Orquestador-Cowork\<p>\` con `entrada\`, `respuestas\` y `salida\`, fuera
  de la raíz de estado (decisión 21). Es lo único que Sebastian conecta en la app de Cowork.
- **Ya no hay `tablero.token`**: el token vive en memoria (D5).
- **Ejecutables**:
  - `agentes.cc.ejecutable` y `herramientas.git` son rutas absolutas. Se validan al iniciar: absoluta, existe y
    es archivo. Se lanzan tal cual con `subprocess`, sin consultar el `PATH`.
  - `.cmd`, `.bat` y `.ps1` solo se aceptan si el prompt va por stdin (cc lo hace).
  - `orq proyecto nuevo` sugiere candidatos en ubicaciones conocidas (`%USERPROFILE%\.local\bin\claude.exe`,
    `%APPDATA%\npm\claude.cmd`, `%ProgramFiles%\Git\cmd\git.exe`) y no escribe la config solo.
  - Al proceso del agente se le pasa el `PATH` del sistema ya filtrado, para que sus herramientas funcionen.
- **Para E2 y E4** quedan anotadas en la referencia (sección 15):
  - Codex: `%LOCALAPPDATA%\OpenAI\Codex\bin\<hash>\codex.exe`, eligiendo la versión más alta.
  - Cursor: `%LOCALAPPDATA%\cursor-agent\agent.ps1` vía `powershell.exe -File`, con el prompt por archivo.

### D3. Registro y máquina de estados

Se usa el modelo y la máquina de estados de la referencia (sección 4), sin los campos de E2 y E3. Cambios del
22-10-2026:
- `esperando_gate → hecha | pendiente` solo por el flujo del tablero. Cancelar una tarea que espera gate se hace
  con `orq tarea`.
- Cualquier archivo que pida decidir un gate (en `decisiones\` o en la entrada de Cowork) se rechaza y deja un
  evento de seguridad.
- Un cambio con una tarea en `esperando_gate` no arranca otras tareas, para que lo revisado no cambie.

### D4. Entrada de Cowork

Carpeta de entrada con `op` crear, editar, cancelar o reintentar. Cada solicitud se aplica entera o nada, con
`.tmp` y renombre, reintentos de 60 s y acuses (referencia, sección 4). Se aceptan trabajos v0 de `tipo: cc`.
Motivo: un solo escritor, validación completa y ningún campo de estado en manos de Cowork.

### D5. Gate por botón

**Flujo:**
1. El detalle de la tarea muestra el `diff --stat` (con los archivos nuevos), el informe y la huella corta.
2. `POST …/preparar` con la huella. El servidor valida la sesión, el CSRF, el origen y la huella, e imprime en la
   terminal un código de 6 dígitos (un solo uso, 120 s, ligado a la tarea, la decisión y la huella).
3. Sebastian escribe el código. Va en `POST …/confirmar` con la huella, el código y la nota.
4. El servidor vuelve a validar y pone la decisión en la cola. El bucle la aplica, deja el historial
   (`por: sebastian`, `via: tablero`, huella, sesión, hora), un evento `gate` y una línea en la terminal.

**Huella**: SHA-256 de:
- El id y el intento.
- El HEAD del worktree.
- `git diff --binary HEAD`.
- Los archivos sin seguimiento, con su SHA-256.
- El SHA-256 de `resultados\<id>.md`.

Se calcula con el `git` de la config, con `GIT_OPTIONAL_LOCKS=0`.

**Mitigaciones evaluadas:**

| Propuesta | Decisión | Qué cubre | Qué no cubre |
|---|---|---|---|
| Token solo en la terminal, sin disco | **Elegida y reforzada**: enlace de entrada de un solo uso, canjeado por una cookie de sesión en memoria | Ya no hay un archivo con el token; el enlace que queda en el historial del navegador no sirve | Leer la consola (`AttachConsole`), la memoria del proceso o la cookie del navegador (DPAPI del mismo usuario) |
| Solo 127.0.0.1 | **Elegida** | Otras máquinas | Procesos locales |
| Origin y CSRF | **Elegida**: `SameSite=Strict`, token CSRF en cabecera, `Origin` y `Host` propios, `Content-Type: application/json` | Páginas web, CSRF y rebinding de DNS | Un proceso local con la sesión pone las cabeceras que quiera |
| Aprobar un estado concreto | **Elegida** (huella en ambos pasos) | Que se apruebe algo distinto de lo que se vio | No impide aprobar el estado vigente si el atacante tiene la sesión y el código |
| Registro y dos pasos | **Elegida, con el segundo paso atado a un código que solo sale en la terminal**, más un bloqueo tras 3 códigos erróneos | Obliga a mirar la terminal en ese momento y deja rastro visible | Un proceso que lea la consola en ese instante |
| Reglas deny (estado, carpeta de Cowork, puerto) | **Elegida como defensa en profundidad**: `Read` y `Edit` denegados en ambas rutas; `curl`, `wget`, `Invoke-WebRequest` e `Invoke-RestMethod` denegados; WebFetch fuera de `--tools` sin red | Lo directo y accidental | En cc sobre Windows es instrucción: un `python -c "urllib…"` lo rodea |
| Canal en memoria, sin archivo de decisiones de gate | **Agregada y elegida** | Que un agente apruebe escribiendo un archivo | — |
| Aviso de integridad del código | **Agregada y elegida**: gates deshabilitados si la instalación tiene cambios sin commit, salvo `--permitir-codigo-modificado` | Un agente que modifique el orquestador para aprobarse | Un agente que además haga commit en el repo del orquestador |
| Escritorio seguro de Windows con contraseña | **Descartada en E1** | Sería la única barrera fuera del alcance del mismo usuario | Maneja la credencial de Sebastian, es complejo con `ctypes`; va con la decisión 6 |
| Puerto aleatorio | **Descartada** | — | Recorrer los puertos de localhost es trivial |
| Nonce por HTTP como segundo paso | **Descartada** | — | Quien tiene la sesión lo recibe en la misma respuesta |

**Lo que no queda cubierto.** Con `cc` en Windows nativo (mismo usuario, sin sandbox), un agente decidido puede,
mediante un intérprete:
- Leer la memoria del orquestador (token, sesión, código vigente) o el buffer de la consola.
- Descifrar las cookies del navegador.
- Leer el portapapeles o capturar la pantalla.
- Automatizar el navegador o enviarle pulsaciones.
- Matar el orquestador y lanzar uno modificado.
- Editar `tareas.json` mientras el orquestador está detenido.
- Hacer commit en el repo del orquestador.

Las defensas suben el costo y dejan rastro, pero no lo impiden. Lo que lo compensa:
- **Barrera final**: ningún gate publica código; el commit lo hace Sebastian a mano.
- **Arreglo de fondo**: la cuenta de Windows dedicada de la decisión 6.

### D6. Adaptador cc

| Aspecto | Definición |
|---|---|
| Comando | `<ruta absoluta de claude> -p --output-format stream-json --verbose --permission-mode dontAsk --permission-prompts none --restricted --tools <lista> --settings <corridas\…\perfil.json> --strict-mcp-config --session-id <uuid>` (o `--resume <uuid>`); prompt por stdin; `cwd` = worktree; `CREATE_NO_WINDOW` |
| Perfil | `permissions.allow` como el v0 (git solo de lectura, `py`, `python`, `openspec`, `pytest`, lectura de archivos, `Skill`); `deny` con las obligatorias en `Bash(...)`, `PowerShell(...)`, `Read(...)` y `Edit(...)` (incluidas la raíz de estado, la carpeta de Cowork, `~/.claude`, `~/.codex` y `~/.cursor`); `disableBypassPermissionsMode: "disable"`; `disableAllHooks: true` |
| Entorno | `PATH` del sistema filtrado; se quitan los secretos y `ANTHROPIC_API_KEY`; se agregan `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` y `DISABLE_AUTOUPDATER=1` |
| Eventos | `system/init` → `inicio`; texto → `mensaje`; Read/Glob/Grep/WebFetch/WebSearch/TodoWrite → `herramienta`; Edit/Write/MultiEdit/NotebookEdit → `archivo`; Bash → `comando`; `result` → `fin`; `is_error` y `rate_limit_event` → `error`; `permission_denials` → `negado` |
| Límite del plan | `rate_limit_event` con `status: "rejected"` (`resetsAt`), `assistant.error == "rate_limit"`, o los textos del v0 más "hit your … limit" |
| Consumo | `result.usage` y `total_cost_usd`, con `costo_estimado: true` |
| Respaldo (decisión 7) | si `--restricted` no funciona con OAuth: `agentes.cc.restricted: false`, que usa `--setting-sources user` con el mismo perfil |
| Versión | mínima 2.1.302, verificada 2.1.306; una mayor se marca "no verificada" |

La interfaz `Adaptador` es la de la referencia (sección 6). E2 y E4 solo agregan módulos.

### D7. Seguridad de cc en E1

| Control | Nivel en Windows nativo | Cómo |
|---|---|---|
| Sin bypass | Duro | revisión de banderas, `dontAsk`, `--restricted` y `disableBypassPermissionsMode` |
| Sin commit, push, reset ni checkout | Instrucción + detección | `allow` solo de lectura, `deny` en Bash y PowerShell, auditoría de git |
| Sin credenciales | Instrucción (entorno: Duro) | `Read`/`Edit` deny, entorno filtrado, worktree sin secretos. **`~/.embudo` sigue en el perfil (riesgo abierto)** |
| Escritura solo en el worktree | Instrucción (herramientas de archivo: Duro) | `--restricted`; Bash sin sandbox |
| Red solo si se pide | Instrucción (WebFetch y WebSearch: Duro) | `--tools` sin web, `deny` de clientes HTTP; incluye el puerto del tablero |

Capas comunes: revisión de banderas, perfil por corrida, entorno filtrado, worktree sin secretos, huellas de
skills con `allowed-tools` o `hooks`, matriz en `inicio`, auditoría de git, Job Object, y rutas de estado y de
Cowork negadas.

### D8. Eventos

Esquema, lista blanca, redacción, topes (4 KB por línea y 2.000 por intento) y rotación (10 MB × 5): referencia,
sección 8. En E1 solo hay normalización de cc.

### D9. Planificador

- **Candidatas**: `pendiente`, `no_antes_de` vencido, cc disponible y no agotado, y cambio libre (nada `en_curso`
  ni en `esperando_gate`). Se ordenan por prioridad y fecha.
- **Preparación**: worktree con candado por repo y el `git` de la config; revisiones de seguridad; foto de git;
  perfil; `Popen` con ruta absoluta; Job Object.
- **Cierre**: auditoría, `diffstat` (archivos nuevos incluidos), huella si hay gate, resultado y salida de Cowork.
- **Límite del plan**: no suma intento, marca `agotado_hasta` y al séptimo límite pasa a `fallida`.
- **Reinicio**: decisión 5, aceptada.

### D10. Tablero

- `ThreadingHTTPServer(("127.0.0.1", puerto))` en un hilo, con estáticos propios.
- **Rutas**: `GET` en todas; `POST` solo en `…/gate/…/preparar` y `…/confirmar`.
- **Páginas**: kanban con filtros, detalle en vivo (polling cada 1,5 s), consumo, y la huella y los botones
  cuando la tarea espera gate.
- **Protección**: CSP, `X-Frame-Options`, `Host` y `Origin`.
- **No escribe archivos**: el `diff --stat` y la huella los calcula el bucle.
- Decisión 4 (sin framework): abierta, con recomendación.

### D11. Lectura del estado por Cowork

`salida\` en la carpeta de Cowork, escrita de forma atómica como máximo 2 s después de cada cambio:
- `estado.json`: tareas sin el prompt (solo su hash), con el gate y su huella corta, el resultado redactado, el
  consumo y las últimas 20 entradas del historial; además, agentes y latido.
- `eventos-recientes.json`: 300 eventos, con textos de 500 caracteres o menos.
- `consumo.json`: totales por agente y día.
- `resultados\<id>.md`.
- `diffstat\<id>.json`.

Todo sale de campos de lista blanca y pasa por la redacción. El orquestador nunca lee `salida\`.

Por qué una carpeta aparte y no `proyectos\<p>\cowork\`:
- Conectarla en Cowork no expone nada más del estado.
- Las reglas deny de los agentes la cubren con una sola ruta.

### D12. Compatibilidad v0 y pruebas

- **v0**: `puente.py` intacto con pruebas de regresión; trabajos v0 en la entrada; `orq importar-v0` simula por
  defecto.
- **Pruebas**: `unittest`. El falso `agente_falso.py --como cc` se lanza por ruta absoluta de `python.exe` (eso
  prueba que no se usa el `PATH`). Red bloqueada salvo loopback, repos sintéticos.
- **Pruebas específicas del gate**: sesión, CSRF, origen, huella vieja, código vencido, bloqueo, archivo de gate
  rechazado, código ausente en HTTP y en disco, e integridad del código.

## Risks / Trade-offs

- **[Mismo usuario, sin sandbox]**: cc puede leer `~/.embudo`, escribir fuera del worktree, usar la red e
  intentar aprobar un gate con un intérprete. → Defensas de D5 y D7, auditoría, salida sin secretos y commit
  manual. Decisiones 6 y 24.
- **[`~/.embudo` en el perfil]**, riesgo aceptado por Sebastian. → `Read` deny (solo la forma directa), red
  apagada por defecto y entorno filtrado.
- **[El código del orquestador es escribible por el agente]** → Aviso de integridad con los gates deshabilitados
  (decisión 23).
- **[El código de la terminal agrega fricción]** → Es el precio de que el segundo paso no viaje por HTTP
  (decisión 20).
- **[`orq tarea` deja archivos falsificables en `decisiones\`]** → Solo reintentar y cancelar, de bajo impacto y
  con rastro (decisión 22).
- **[`--restricted` sin verificar con OAuth]** → Respaldo configurable (decisión 7).
- **[Flags que cambian con las actualizaciones]** → Versión mínima, "no verificada" y `DISABLE_AUTOUPDATER`.
- **[Detección del límite por texto]** → Varias señales; un fallo de detección gasta un intento.
- **[Windows traba archivos abiertos]** → Reintentos y lectores que abren y cierran.
- **[Redacción incompleta]** → Lista blanca y topes, también en la salida de Cowork.
- **[Cowork conecta una carpeta equivocada]** → La carpeta de Cowork está fuera de la raíz y el orquestador
  detecta escrituras externas en `tareas.json`.

## Migration Plan

1. Implementar E1 sin tocar `puente.py`; las pruebas de regresión del v0 van primero.
2. Sebastian configura las rutas absolutas de `claude` y `git` y crea un proyecto sintético.
   - Conecta en Cowork solo `Orquestador-Cowork\<p>`.
   - Corre `docs/verificacion-manual.md` (cc con `--restricted` y OAuth, gate por botón en el navegador).
3. Embudo sigue con su v0.
4. Vuelta atrás: detener `orq correr` y usar `puente.py`. Las dos carpetas nuevas se pueden borrar sin afectar
   ningún repo.

## Open Questions

- Código de salida de cc al llegar al límite del plan. Solo ajusta el adaptador.
- Si `--restricted` acepta OAuth (decisión 7). Cambia una opción de configuración, no las specs.
