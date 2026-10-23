# Design

## Context

Ver `proposal.md` (Why). La referencia larga sigue en `docs/diseno-orquestador.md` y el diseño de E1 en
`openspec/changes/archive/2026-10-22-orquestador-v1/design.md`. Las decisiones siguen la numeración de E1 (25 en
adelante).

Estado actual relevante:
- **`cc` ya lanza con `--strict-mcp-config`** (`adaptadores/cc.py`). El hallazgo vino del paso 2 de
  `docs/verificacion-manual.md`, que no lleva esa bandera ni `--settings`. No se sabe todavía si las corridas reales
  exponían los conectores: lo responde el paso 7 nuevo (D3).
- **`dontAsk` ya niega lo que no está en `allow`**, y el perfil no tiene reglas `mcp__`. Eso no basta: el modelo ve
  las herramientas y sus descripciones, un `permitir_extra` del proyecto podría abrirlas y la doc no dice cómo se
  combinan con los permisos por herramienta que el conector trae desde claude.ai. No se cuenta como defensa.
- **`corrida.py` ya corta corridas** (cancelación y tiempo) cerrando el Job Object. El planificador manda
  `Desenlace("seguridad")` y `("violacion")` a `fallida` sin reintentos, pero un `resultado.error` con clase
  `seguridad` hoy cae en `Desenlace("error")` (`planificador.py`, final de `_ejecutar`) y gasta reintentos.
- **El tablero** sirve `kanban.html`, `detalle.html` y `consumo.html`. El token de entrada vive en memoria, se canjea
  una vez y no vence. La sesión dura hasta reiniciar el proceso.
- **Mismo usuario, sin sandbox** (E1, D5): un agente con `py` puede leer la consola del orquestador, la memoria del
  navegador y sus cookies, y correr `py orq.py …` (está en `Bash(py *)`). Lo nuevo no debe abaratar esos ataques.

### Verificado en la documentación oficial (22-10-2026)

| Hecho | Fuente (code.claude.com/docs/en/…) | Estado |
|---|---|---|
| `ENABLE_CLAUDEAI_MCP_SERVERS=false`: "stop Claude Code from fetching claude.ai MCP servers" | `env-vars` (fila) y `mcp`, "Disable claude.ai connectors" | Verificado |
| `disableClaudeAiConnectors: true`: "neither fetches nor connects" los conectores. "A `true` in any settings file applies". Alcance "Any file" = usuario, proyecto, local y administrado | `settings-reference` (entrada) | Verificado. **No nombra** `--settings` como fuente |
| Ambos actúan solo sobre los conectores que Claude Code trae por su cuenta (terminal, VS Code, Agent SDK); no sobre los que entrega la app de escritorio ni una sesión en la nube | `mcp`, "How connectors reach Claude Code" | Verificado |
| `--tools`: "doesn't affect MCP tools; to deny those too, use `--disallowedTools "mcp__*"`" | `cli-reference` (fila `--tools`) | Verificado |
| `--disallowedTools`: `"mcp__*"` "removes every MCP tool" del contexto | `cli-reference` (fila) | Verificado |
| `permissions.deny: ["mcp__*"]` en un archivo de settings: "matches every MCP tool across all servers" y la quita del contexto | `permissions`, "Tool name wildcards" | Verificado |
| `--strict-mcp-config`: "Only use MCP servers from `--mcp-config`, ignoring all other MCP configurations"; en otra página: "limits which configuration files load" | `cli-reference` y `managed-mcp` | **No dice** si excluye los conectores |
| Un `managed-mcp.json` suprime los conectores, pero con `--strict-mcp-config` Claude Code "exits at startup" | `managed-mcp`, "Servers passed with --mcp-config or --strict-mcp-config" | Verificado: no sirve aquí |
| `serverName` en `deniedMcpServers` "is not a security control" (el nombre de un conector puede cambiar) | `managed-mcp` | Verificado |
| Los conectores se traen solo con sesión de suscripción de claude.ai (no con `ANTHROPIC_API_KEY` ni con el token de `setup-token`) | `mcp`, "Use MCP servers from claude.ai" | Verificado. No aplica: el plan se usa con OAuth |
| Los nombres de los conectores son `mcp__claude_ai_<servidor>__<herramienta>` | `permissions` | Verificado (calza con el hallazgo) |
| `system/init` trae `tools: string[]` y `mcp_servers: {name, status, source?}[]` (campos obligatorios del tipo) | `agent-sdk/typescript`, `SDKSystemMessage` | Verificado |
| `rate_limit_event.rate_limit_info` trae `status`, `resetsAt?: number` y `utilization?: number` | `agent-sdk/typescript`, `SDKRateLimitEvent` | Existe. **No dice** la escala, la ventana ni cada cuánto llega |
| `claude auth status` "Exits with code 0 if logged in, 1 if not" | `cli-reference` | Verificado |

## Goals / Non-Goals

**Goals:**
- Ninguna corrida sigue si el agente tiene herramientas o servidores MCP que no se pidieron, comprobado en cada
  corrida y no una sola vez.
- Un tablero que se entienda sin conocer la máquina de estados, con los textos armados en Python y probados.
- Abrir el tablero sin copiar enlaces y sin canales nuevos que entreguen una sesión.
- Instalar en otro PC con un comando que no lee credenciales ni toca git.

**Non-Goals:**
- MCP declarados por tarea (E3): en este change todo MCP queda apagado.
- Revisión automática por otro agente (E2): aquí solo se lee la revisión si Cowork la pidió como tarea.
- Conteo de pruebas ("412 en verde"): no se guarda la salida de los comandos; llega con el contrato de respuesta (E3).
- Arranque con Windows, aislamiento con otra cuenta (decisión 6) y cambiar la política de ejecución.

## Decisions

### D1. Prevención: apagar conectores y MCP en cada corrida de `cc` (parte A)

Todas las capas van juntas, porque la doc no garantiza que una sola baste en esta versión:

| Capa | Dónde | Qué cubre según la doc | Duda |
|---|---|---|---|
| `ENABLE_CLAUDEAI_MCP_SERVERS=false` | entorno del agente, puesta al final (pisa lo heredado) | no trae los conectores | ninguna |
| `disableClaudeAiConnectors: true` | perfil (`--settings`), también en el respaldo sin `--restricted` | no los trae ni los conecta | si `--settings` cuenta como fuente |
| `--disallowedTools "mcp__*"` | comando | quita del contexto toda herramienta MCP | ninguna |
| `"mcp__*"` en `permissions.deny` | perfil | lo mismo, desde el archivo de settings | ninguna |
| `--strict-mcp-config` (ya estaba) | comando | ignora los MCP de configuración | si cubre los conectores |

- El núcleo fija las capas por agente en `seguridad.CAPAS_OBLIGATORIAS`: `--strict-mcp-config`, el par
  `--disallowedTools mcp__*` y `ENABLE_CLAUDEAI_MCP_SERVERS=false` (sin otra copia de la variable con otras
  mayúsculas). `seguridad.revisar_lanzamiento` las exige: si falta alguna, o si el agente no tiene entrada en la
  tabla, no se lanza (clase `seguridad`). Las fija el núcleo y no el adaptador, para que un adaptador mal armado o
  uno nuevo no pueda saltarse la capa por omisión.
- `proyectos.py` rechaza `permitir_extra` con reglas que empiecen con `mcp__` (proyecto inactivo con el motivo).
- `CLAUDE_CODE_MCP_STARTUP_WAIT_MS` no se toca: el corte de D2 no depende de cuánto espere el agente.
- **Descartado**:
  - `managed-mcp.json` vacío: suprime los conectores, pero hace que `claude --strict-mcp-config` termine al arrancar
    y exige permisos de administrador.
  - `deniedMcpServers` por nombre ("claude.ai Google Drive"): la doc dice que no es un control de seguridad.
  - Correr con `ANTHROPIC_API_KEY` o un token de `setup-token` para que no se traigan: cambia la facturación del
    plan y obliga a guardar un secreto.
- **Opcional, fuera del repo** (decisión 26): `disableClaudeAiConnectors: true` en
  `C:\Program Files\ClaudeCode\managed-settings.json`. Es la fuente administrada, que la doc sí garantiza, pero
  apaga los conectores en todas las sesiones de Claude Code de Sebastian (no en Cowork ni en la app de escritorio,
  según la tabla de la doc) y pide administrador.
- Cuando llegue E3, `mcp__*` pasa a ser "todo `mcp__` salvo los declarados". Queda anotado en
  `docs/referencia/requisitos-e2-e4.md`.

### D2. Comprobación que falla cerrada en cada corrida (parte A)

- **Dónde**: en el núcleo (`corrida.py`), no en el adaptador. Ningún adaptador decide si se salta la revisión.
  - `Lanzamiento` gana `herramientas_esperadas`: la lista pedida en `--tools` más las toleradas del adaptador.
  - `cc.normalizar` traduce `system/init` a `inicio` con `herramientas` (de `tools`) y `mcp` (de
    `mcp_servers[].name`). Si `tools` o `mcp_servers` no son listas, entrega `herramientas: None`.
- **Al iniciar**, `corrida.py` corta (cierra el Job, igual que el tiempo máximo) si:
  1. sobra cualquier nombre respecto de `herramientas_esperadas`, con o sin `mcp__`;
  2. `mcp` no está vacío, aunque el servidor esté `pending` o `failed`;
  3. `herramientas` es `None` (el aviso no trajo listas);
  4. llega un `tool_use` antes de cualquier `inicio`.
  Faltar herramientas no es motivo de corte (por ejemplo, `Glob` ausente en una versión). Una línea que la
  revisión o el adaptador no pueden leer (excepción) también corta, con clase `seguridad`: nunca deja al agente
  corriendo sin vigilancia. La revisión lee el stream-json de Claude Code; un agente nuevo necesita la suya y su
  entrada en `CAPAS_OBLIGATORIAS` antes de poder lanzarse.
- **Durante la corrida**: cada `tool_use` se compara con lo visto al iniciar. Es **detección**: el `assistant`
  llega antes de que la herramienta corra, pero el corte puede perder la carrera. El panel y la matriz lo dicen.
- **Desenlace**:
  - `resultado.error = {"clase": "seguridad", ...}` y `_ejecutar` lo traduce a `Desenlace("seguridad")` (línea nueva
    junto a `limite_uso`), que ya lleva a `fallida` sin reintentos. Sin esa línea la tarea reintentaría.
  - La auditoría de git corre igual después; si encuentra algo, gana `violacion`, como hoy.
  - Mensaje: "herramientas no pedidas: mcp__claude_ai_Google_Drive__share_file, … (N más)". Los nombres no son
    secretos. Cowork recibe solo la clase.
- **Tope del evento**: la comparación usa la lista completa en memoria; el evento `inicio` guarda hasta 40 nombres
  y `herramientas_omitidas: N`, para no pasar `TOPE_LINEA` (4096) de `eventos.py`.
- **Herramientas toleradas de `cc`**: constante en `cc.py`, con versión y fecha por nombre, y ningún `mcp__`
  (una prueba lo exige).
  - Empieza vacía. Se llena con lo que reporte el paso 7 (la doc anticipa `EndConversation`, que `--tools` no
    quita, y las de tareas si `TodoWrite` las activa).
  - Si una versión nueva de Claude Code agrega una herramienta, la corrida falla cerrada y el error la nombra
    (decisión 25).
- **El falso**: `init` emite como `tools` lo que recibió en `--tools` y `mcp_servers: []`. Guiones nuevos:
  `conectores`, `mcp_pendiente`, `herramienta_tarde`, `sin_init` y `uso_plan`. Cada prueba nueva falla sin el
  cambio, porque hoy esas corridas terminan `ok`.
- **Matriz**: control nuevo "conectores y MCP no declarados", `duro` en `cc` (capas documentadas más el corte antes
  de la primera acción del modelo).
- **Descartado**:
  - Revisar solo el prefijo `mcp__`: deja pasar herramientas nuevas que nadie revisó.
  - Una corrida de sondeo al arrancar: gasta plan y no protege cada corrida (la sesión de claude.ai cambia).

### D3. Paso 7 de `docs/verificacion-manual.md`: "Conectores de claude.ai" (parte A)

PowerShell, con `ConvertFrom-Json` por línea y filtro por `type`/`subtype`, sin dependencias:
- (a) El comando del paso 2: anotar `tools` y `mcp_servers` de `system/init` (reproduce el hallazgo).
- (b) a (e) Cada capa sola: `--strict-mcp-config`; `$env:ENABLE_CLAUDEAI_MCP_SERVERS="false"`; `--settings` con
  `{"disableClaudeAiConnectors":true}`; `--disallowedTools "mcp__*"`. Se anota cuál basta sola.
- (f) El comando completo del adaptador: `tools` igual a lo pedido más lo tolerado, y `mcp_servers` vacío.
- (g) Una tarea real por el orquestador: el `inicio` sin `mcp__` y la tarea sin error de seguridad.
- (h) Si aparece `rate_limit_event` con `utilization`, anotar el valor y el `status`.
- Cada subpaso usa `"Responde solo: hola"`: ningún subpaso le pide al modelo usar una herramienta.

### D4. Datos que faltan en la API (parte B)

`GET /api/tablero?proyecto=<p>` reemplaza a `/api/tareas` en la página principal. `/api/tareas` se mantiene por
compatibilidad, `/detalle` se elimina y `/api/tareas/<p>/<id>` sigue alimentando el panel. Los textos se arman en
Python (`vistas.py` y `frases.py`) y el JS solo los pinta: así el lenguaje simple se prueba con `unittest`.

```json
{"momento": "…", "proyecto": "orquestador", "proyectos": ["…"], "gates": {"deshabilitados": null},
 "turno": [{"id": "E2-4r", "titulo": "Adaptador de Codex", "explicacion": "…", "archivos": 6,
            "pruebas": {"ok": true, "en": "…"},
            "revision": {"veredicto": "sin_reparos", "resumen": "…", "agente": "cc"}}],
 "agentes": [{"agente": "cc", "nombre": "Claude Code", "estado": "trabajando", "tarea": "Adaptador de Codex",
              "frase": "Editó adaptadores/codex.py", "frase_en": "…", "motivo": null, "reinicio": null,
              "hoy": {"minutos": 47, "tareas": 3}, "plan": {"uso": 0.62, "visto_en": "…"}}],
 "plan": [{"cambio": "etapa-2", "listas": 3, "total": 6, "nota": "termina cuando apruebes la 4",
           "estaciones": [{"id": "E2-4", "titulo": "…", "agente": "codex", "forma": "espera",
                           "texto": "Te espera"}]}]}
```

| Dato que falta | De dónde sale |
|---|---|
| Qué se aprueba | campo nuevo y opcional `explicacion` (≤ 300, una línea) que escribe Cowork. Si la tarea en gate tiene `revisa`, se usan el título y la explicación de la revisada. Sin ella, la sección no aparece |
| Evidencia | total del `diffstat` y el último `comando` de pruebas del intento (`unittest` o `pytest`) con su estado, sin contar casos |
| Resumen de la revisión | tarea con `revisa: <id>`: veredicto de la primera línea de su informe (`Veredicto: sin reparos\|con reparos\|no concluyente`) y los 500 caracteres siguientes, redactados. Sin tarea de revisión: `null`, que se lee "Sin revisión" |
| Frase de la última acción | último evento del intento en curso, pasado por `frases.py`, con su hora |
| Consumo del día | minutos y tareas de las corridas que empezaron hoy (fecha local), más la que está en curso; `plan.uso` solo si el agente lo informó (D5) |
| "Revisado hace N s" | `momento` de la instantánea |

- **Gate en la revisión**: un cambio no corre nada mientras una tarea espera gate (E1). Por eso la revisión es una
  tarea aparte, después de la revisada, y el gate va en la revisión. La huella cubre el worktree entero del cambio,
  así que se aprueba lo mismo (decisión 29).
- **Orden de las estaciones**: topológico por dependencias; en empate, por `creada` y luego por `id`. Una
  `bloqueada` dice "Espera a T-2", o "Espera a la anterior" si T-2 es la estación previa.
- **Cambios visibles**: los que tienen tareas sin terminar o terminaron en las últimas 24 horas.

### D5. Uso del plan (partes A y B)

- `cc.normalizar` lee `utilization` y `resetsAt` de todo `rate_limit_event`, no solo de los `rejected`.
- `Resultado.uso_plan = {uso, visto_en, reinicia}`, y el planificador guarda el último por agente en `agentes.json`.
- **Normalización**: de 0 a 1 se usa tal cual; mayor que 1 y hasta 100 se divide por 100; otro valor da `null`.
  La escala real se confirma en el paso 7(h).
- **Nunca se estima un porcentaje** (decisión 28). Sin dato, la fila muestra minutos y tareas del día, sin barra.
  Con dato: "Plan: 62 % usado · según Claude Code, hace 5 min".

### D6. Frases (`orquestador/frases.py`)

Funciones puras, sin E/S. Las rutas van relativas al worktree y con `/`.

| Evento | Frase |
|---|---|
| `inicio` | "Empezó" / "Retomó su sesión" |
| `herramienta` leer · buscar · web · skill · tareas | "Leyó <ruta>" · "Buscó en el código" · "Consultó la web" · "Usó la skill <x>" · "Ordenó sus pendientes" |
| `archivo` editar · escribir | "Editó <ruta>" · "Escribió <ruta>" |
| `comando` de pruebas | "Corrió las pruebas" / "Corrió las pruebas: fallaron" |
| `comando` git de lectura · `openspec validate` · otro | "Revisó git" · "Validó con OpenSpec" · "Corrió un comando" (el texto va en detalles técnicos) |
| cualquier `negado` | "Intentó <verbo o comando corto> y se le negó" (siempre visible) |
| `fin` | "Terminó y entregó su informe" / "Terminó con error" |
| `error` | `limite_uso`: "Se le acabó el plan; sigue a las HH:MM". `seguridad`: "Se detuvo por seguridad". `violacion`: "Se detuvo: tocó git". `timeout`: "Se le acabó el tiempo". `agente`: "Falló el agente" |
| `gate` | "Aprobaste" / "Rechazaste con un comentario" |
| `mensaje` | sin frase |

- Las repeticiones seguidas se juntan ("Editó tablero.py (3 veces)"). El panel muestra las últimas 60 frases.
- Estados de estación, de la misma tabla: `hecha` "Hecha"; `en_curso` "Trabajando, N min"; `esperando_gate`
  "Te espera"; `bloqueada` "Espera a …"; `pendiente` "En cola", "Plan agotado · sigue a las HH:MM" o "Agente
  apagado"; `fallida` "Falló: <frase de la clase>"; `cancelada` "Cancelada".

### D7. Estáticos de la página (parte B)

- **Archivos**: `tablero.html` en `/`, más `app.css` y `app.js` reescritos. `consumo.html` se queda, con el CSS
  nuevo, y se enlaza desde "Ahora mismo". `kanban.html` y `detalle.html` dejan de servirse y Sebastian los borra.
- **Lo que la maqueta trae en línea y cómo se reemplaza** (la CSP no cambia):
  - `style="--color:…"` → clases `.ag-cc`, `.ag-codex`, `.ag-cursor` y `.ag-otro`, que fijan `--color`.
  - `style="width:62%"` de la barra → `<meter min="0" max="1">`.
  - Leyenda con estilos en línea → clases de estado (`.hecha`, `.trabajando`, `.espera`, `.bloqueada`, `.fallida`).
  - El `<script>` final → `app.js`. Todo texto entra con `textContent`; nunca `innerHTML` con datos.
- **Fuentes**: Bahnschrift para títulos y Segoe UI para texto, con `system-ui` de respaldo. Sin `@font-face`.
- **Polling**: `/api/tablero` cada 3 s; con el panel abierto, eventos cada 1,5 s y detalle cada 3 s, como hoy.
- **Panel**: `role="dialog"`, foco en la ×, se cierra con Escape, la × o un clic fuera. Al aprobar aparece el campo
  del código; `preparar` y `confirmar` no cambian. Lo técnico (id, intentos, historial, niveles, consumo, informe)
  va plegado en "Detalles técnicos".
- **Sin sesión**: `/static/*` se sirve sin sesión (no trae datos) para que la página 401 tenga estilo sin CSS en
  línea. `/` sin sesión responde 401 con una página fija: "Pulsa Enter en la ventana del orquestador para entrar".
- **Accesibilidad**: el estado nunca va solo por color (forma más texto), contraste AA, `prefers-reduced-motion` y
  teclado.

### D8. Enlace nuevo: evaluación de las tres opciones (parte C)

El problema de fondo: cualquier vía por la que un segundo proceso pida un enlace la puede usar también un agente,
porque corre con el mismo usuario. Y `py orq.py …` está permitido en el perfil (`Bash(py *)`): si `orq abrir`
pudiera traer un enlace, una inyección en el prompt bastaría para tomar la sesión con un comando permitido, sin
escribir código de ataque.

| Opción | A favor | En contra | Decisión |
|---|---|---|---|
| Tubería con nombre con ACL; `orq abrir` pide el enlace | No hay que ir a la ventana | La ACL distingue usuarios, no procesos: el agente abre la tubería igual que `orq abrir`. Revisar el PID del cliente (`GetNamedPipeClientProcessId` más `IsProcessInJob`) se rodea lanzando fuera del Job (Programador de tareas, WMI `Win32_Process.Create`). Con la tubería, tomar la sesión pasa de leer la consola o la memoria a correr `py orq.py abrir`. Pide `ctypes` delicado (descriptores de seguridad) | Descartada **mientras los agentes corran con el usuario de Sebastian**. Sirve el día que corran con otra identidad (decisión 6) |
| Enter en la ventana del orquestador | Exige estar frente a la ventana, el mismo canal que ya protege el código del gate. Solo un hilo que lee la entrada estándar: ningún canal nuevo. Deja rastro (se abre el navegador y la terminal anota la sesión) | Hay que ir a la ventana. Un proceso del mismo usuario puede inyectar teclas en la consola (`WriteConsoleInput`) y leer su búfer, pero ese poder ya le da hoy el código del gate | **Elegida** |
| Cookie que dure mientras corra el proceso | Cerrar y reabrir el navegador no pide nada | Del lado del servidor ya dura eso. Lo nuevo sería `Max-Age`, y entonces el navegador la guarda en disco, legible para el mismo usuario (Firefox en texto; Chromium cifrada, pero no es frontera ante el mismo usuario). No resuelve otro navegador ni el reinicio | Descartada: la cookie sigue de sesión (decisión 31) |

- **`orq abrir`** no obtiene enlaces:
  - Lee el candado (solo lectura). Si `orq correr` vive, abre `http://127.0.0.1:<puerto>/` y explica el Enter. Si el
    navegador conserva la cookie, entra directo; si no, ve la página 401 con la misma instrucción.
  - El candado gana el campo `puerto` (lo escribe `orq correr` al levantar el tablero). Sin él, se usa el de la
    config.
  - Si no corre: "El orquestador no está corriendo: usa el acceso directo o `orq correr --abrir`", código 1.
- **Tokens**: clase `Entradas` en `tablero.py` con un solo token vigente, que vence a los 5 minutos (decisión 30) y
  se anula al generar otro.
- **Hilo de la terminal** (`orquestador/acceso.py`, lo arranca `orq.py`; el servidor HTTP no lanza procesos):
  - Solo si `sys.stdin.isatty()`. Enter: enlace nuevo, se imprime y se abre con `webbrowser.open`. `x` y Enter:
    cierra todas las sesiones (respuesta rápida si aparece una que Sebastian no abrió).
  - Sin TTY, avisa una vez. Ctrl+C sigue llegando al hilo principal.
- **Aviso de sesión**: `[tablero] sesión nueva 14:02 (2 abiertas)`, sin token ni cookie.
- **`--abrir`**: abre el enlace inicial. Residual: la URL pasa por la línea de comandos del navegador durante
  milisegundos. Si alguien la canjea antes, el navegador de Sebastian recibe 401 ("enlace ya usado: si no fuiste
  tú, pulsa x y Enter en el orquestador").

### D9. Acceso directo `Orquestador.cmd` (parte C)

```bat
@echo off
rem orq-acceso-directo v1 (lo genera orq instalar; no lo edites a mano)
chcp 65001 >nul
title Orquestador
cd /d "%USERPROFILE%\work\orquestador"
"%LOCALAPPDATA%\Programs\Python\Python312\python.exe" "%USERPROFILE%\work\orquestador\orq.py" correr --abrir
if errorlevel 1 pause
```

- **Por qué `.cmd`** y no `.lnk`: no necesita COM ni PowerShell y se revisa a simple vista.
- **Rutas**: Python es `sys.executable` de quien corre `orq instalar`, y el repo, la carpeta de `orq.py`. Si una ruta
  cae bajo `%USERPROFILE%` o `%LOCALAPPDATA%`, se escribe con la variable: el archivo queda ASCII en el caso común y
  `cmd` expande la ruta real aunque tenga tildes. Si no, va en UTF-8 sin BOM, con `chcp 65001` antes.
- **Se rechazan** rutas con `%`, `"`, `!`, `^` o saltos de línea: en un `.cmd`, `%` se expande incluso entre comillas.
  El motivo va a los pendientes.
- **Escritorio**: `SHGetKnownFolderPath(FOLDERID_Desktop)` con `ctypes`, porque puede estar en OneDrive. Si falla,
  `%USERPROFILE%\Desktop`.
- **Propiedad**: solo se reescribe si la línea `rem` es la marca. Si el contenido es igual, no se toca (ni la fecha).
- **Segunda instancia**: `orq correr --abrir` con el candado ocupado hace lo de `orq abrir` y termina con 1; el
  `pause` deja leer el aviso.
- **Cerrar la ventana**: el Job de cada corrida mata a los agentes y el candado queda abandonado; el próximo arranque
  lo toma (spec `proyectos`).
- Nada en Inicio, en el registro `Run` ni en el Programador de tareas.

### D10. `orq instalar` (parte D)

- **Módulo** `orquestador/instalar.py`: un plan de pasos `Paso(nombre, estado, detalle, pendiente)` que se calcula
  sin escribir. Estados: "ya estaba", "crearía", "creado", "falta" y "revisar". `--aplicar` ejecuta solo los
  "crearía".
- **Inyectables en pruebas**: rutas base (`USERPROFILE`, `LOCALAPPDATA`, `APPDATA`, `ProgramFiles`), el ejecutor y
  el escritorio.
- **Detección** (rutas conocidas, nunca el `PATH`):

| Herramienta | Rutas | Confirmación | Sesión |
|---|---|---|---|
| Python | `sys.executable` (≥ 3.12) y `py.exe` (informativo) | `sys.version_info` | — |
| git | `%ProgramFiles%\Git\cmd\git.exe`, `%LOCALAPPDATA%\Programs\Git\cmd\git.exe` | `--version` | — |
| claude | `%USERPROFILE%\.local\bin\claude.exe`, `%APPDATA%\npm\claude.cmd` | `--version` | `auth status`, código 0 o 1 (doc) |
| codex | `%LOCALAPPDATA%\OpenAI\Codex\bin\*\codex.exe`: la versión más alta; en empate, la carpeta más reciente | `--version` | `login status`, código 0 o 1 (según `docs/diseno-orquestador.md`, leído del código de Codex) |
| Cursor | `%LOCALAPPDATA%\cursor-agent\agent.ps1` | solo que exista: el `.ps1` no se ejecuta | "se verifica en E4" (códigos de `agent status` sin documentar) |

- **Cómo se ejecutan**: salida estándar y de error a `DEVNULL` (no se leen), entrada `DEVNULL`, entorno filtrado
  (`seguridad.entorno_filtrado`), `CREATE_NO_WINDOW` y 10 s como máximo. Para `--version` se lee solo la versión.
  Nunca se abre un archivo de credenciales.
- **Escrituras con `--aplicar`**: la raíz de estado; `config.json` solo si no existe, armado desde
  `ejemplos/config.example.json` con `json` y las rutas detectadas de claude y git; `%USERPROFILE%\Orquestador-Cowork`;
  y `Orquestador.cmd` (D9). Un `config.json` existente no se toca: las diferencias van a los pendientes.
- **No escribe**: git, la política de ejecución, el registro de Windows ni la carpeta de Inicio.
- **Remoto**: `git config --get remote.origin.pushurl` en la carpeta del repo, con `GIT_OPTIONAL_LOCKS=0`.
- **Pendientes** (lista numerada, con el comando exacto cuando lo hay): conectar `Orquestador-Cowork\<p>` en Cowork;
  `orq proyecto nuevo …`; `claude auth login` si no hay sesión; `codex login` si está sin sesión (para E2);
  `git remote set-url --push origin no-push` si el push sigue habilitado; correr `docs/verificacion-manual.md`.
- Si un agente corre `py orq.py instalar --aplicar`, no pasa nada grave: no pisa nada existente.

### D11. Remoto en GitHub sin push por defecto (parte D)

- **Riesgo**: con `origin` apuntando al repo privado y la credencial guardada en Git Credential Manager, un agente
  con intérprete puede correr `git push`. La regla `Bash(git push)` es solo instrucción, y la auditoría de git no ve
  un `git push <url>`, que no mueve referencias locales.
- **Capas**:
  1. `remote.origin.pushurl = no-push`: el `git push` sin URL falla ("'no-push' does not appear to be a git
     repository"). Corta lo accidental. `orq correr` avisa al arrancar si no está anulada (junto al aviso de
     integridad). Si el repo del orquestador es además un proyecto, la huella de `.git/config` de la auditoría
     detecta que un agente la cambió; si no lo es, solo queda el aviso del próximo arranque.
  2. Sebastian publica solo con la URL completa: `git push git@github.com:<usuario>/orquestador.git main`.
  3. **La barrera real es la credencial**: si está guardada sin pedir nada, un agente también puede hacer
     `git push <url completa>`. Recomiendo una llave de despliegue (deploy key) con escritura solo para este repo,
     con frase de paso y sin `ssh-agent`: cada push la pide en la terminal y un agente sin consola no la puede
     teclear (decisión 32). Para clonar en un PC nuevo basta HTTPS de solo lectura o la misma llave.
  4. Si la cuenta de GitHub es Pro, una regla en `main` que exija pull request. En GitHub Free las reglas de rama y
     los rulesets solo existen en repos públicos (docs.github.com, "About rulesets").

### D12. `docs/INSTALAR.md` (parte D)

En PowerShell, en este orden:
1. Requisitos: Python 3.12 con el lanzador `py`, Git for Windows, Claude Code nativo; Codex y Cursor opcionales.
2. **Política de ejecución**: `Get-ExecutionPolicy -List`. Los `.ps1` están bloqueados y no hace falta cambiarlo:
   se usan `openspec.cmd`, `py` y el `.cmd`. `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` queda para E4
   con Cursor (decisión 33).
3. Llave de despliegue y clonar: `git clone git@github.com:<usuario>/orquestador.git`; luego
   `git remote set-url --push origin no-push`.
4. `py -3.12 .\orq.py instalar` (simulación) y después `--aplicar`.
5. Sesiones: `claude auth login`; `codex login` si se usará en E2.
6. `py -3.12 .\orq.py proyecto nuevo …` y conectar solo `Orquestador-Cowork\<proyecto>` en Cowork.
7. `docs/verificacion-manual.md`, pasos 1 a 7.
8. Publicar: `git push git@github.com:<usuario>/orquestador.git main`, con la frase de paso.
9. Vuelta atrás: qué carpetas y archivos borrar.

## Decisiones para Sebastian

25. **Herramienta propia desconocida, sin `mcp__`**: ¿falla cerrada o solo aviso? Recomiendo **falla cerrada**. Una
    versión nueva de Claude Code puede frenar las tareas hasta verificarla, pero esa versión ya sale "no verificada".
26. **Capa administrada** (`managed-settings.json` con `disableClaudeAiConnectors`): recomiendo **no ponerla ahora**.
    Ponerla solo si el paso 7 muestra que la variable no basta, o si no usas conectores en Claude Code.
27. **`orq abrir` no entrega enlaces** (pediste que lo hiciera): recomiendo Enter en la ventana del orquestador, con
    `orq abrir` que solo abre `/`. Revisar la tubería con ACL cuando los agentes corran con otra cuenta.
28. **Consumo del día**: porcentaje solo si Claude Code lo informa; si no, minutos y tareas. Recomiendo no estimar.
29. **Revisión**: tarea aparte con `revisa`, gate en la revisión y veredicto en la primera línea del informe.
    Recomiendo esto ahora; que la revisión se cree sola queda para E2.
30. **Vencimiento del enlace**: 5 minutos. Menos incomoda; más alarga la ventana.
31. **Cookie**: sigue de sesión, sin `Max-Age`. Cerrar el navegador pide Enter de nuevo.
32. **Credencial de GitHub**: llave de despliegue con frase de paso y sin `ssh-agent`. Alternativa: token de grano
    fino tecleado en cada push con `-c credential.helper=`. Recomiendo la llave.
33. **Política de ejecución**: no cambiarla ahora; `RemoteSigned` para el usuario se decide en E4.
34. **Borrar `kanban.html` y `detalle.html`** en el mismo commit del apply (lo haces tú).

## Risks / Trade-offs

- **[Ninguna capa apaga los conectores en la versión instalada]** → El corte de D2 frena la corrida igual; el paso 7
  dice qué capa sirve.
- **[Una versión nueva agrega una herramienta propia]** → Falla cerrada con el nombre en el error (decisión 25).
- **[La vigilancia durante la corrida llega tarde]** → Es detección; lo que previene son D1 y el corte al iniciar.
- **[Un agente modifica `cc.py` para tolerar `mcp__`]** → Riesgo de E1 (aviso de integridad, gates
  deshabilitados), más la prueba de que la lista tolerada no tiene `mcp__`.
- **[Inyección de teclas en la consola]** → El mismo poder ya lee el código del gate. Quedan el rastro, la tecla `x`
  y la cuenta dedicada (decisión 6).
- **[URL del enlace en la línea de comandos del navegador]** → Un solo uso, 5 minutos y aviso de sesión.
- **[El `.cmd` y el codepage]** → Variables de entorno en las rutas, `chcp 65001` y una prueba con `cmd.exe` real en
  una carpeta con tildes y espacios.
- **[Push con la URL completa y la credencial guardada]** → Solo lo frena la credencial (decisión 32).
- **[`utilization` con otra escala o que no llega]** → Normalización con límites, `null` sin dato y paso 7(h).
- **[El rediseño pierde información del kanban]** → Sigue en "Detalles técnicos" y `/consumo`, y `/api/tareas`
  se mantiene.

## Migration Plan

1. Implementar A primero (tareas 1.x). Sebastian corre el paso 7 con el binario real y llena la lista tolerada.
   Hasta entonces, toda tarea de `cc` falla cerrada (es lo esperado).
2. Implementar B, C y D. Sebastian borra `kanban.html` y `detalle.html` y hace el commit.
3. En el PC nuevo: `docs/INSTALAR.md`.
4. **Vuelta atrás**: A solo se afloja editando código. B y C se revierten con el commit anterior: el estado en disco
   no cambia de formato (`explicacion`, `revisa`, `uso_plan` y `puerto` del candado son opcionales). D solo crea
   carpetas y archivos que se pueden borrar.

## Open Questions

Ninguna cambia las specs ni las tareas: las responde el paso 7.
- ¿`--strict-mcp-config` excluye por sí solo los conectores? ¿`disableClaudeAiConnectors` vale desde `--settings`?
- ¿Qué herramientas propias agrega Claude Code 2.1.306 a `--tools` (contenido de la lista tolerada)?
- ¿Trae `mcp_servers` algún servidor propio de Claude Code aun con todo apagado? Si es así, se decide si se tolera.
- ¿En qué escala viene `utilization`, de qué ventana es y si llega con `status: "allowed"`?
