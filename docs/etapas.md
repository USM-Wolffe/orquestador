# Etapas del orquestador v1

Decisión de Sebastian del 22-10-2026: el diseño completo (`docs/diseno-orquestador.md`) se implementa en 4
changes de OpenSpec. Cada etapa se cierra con su gate, el commit de Sebastian y el archive antes de abrir la
siguiente. Los requisitos de E2 a E4 están en `docs/referencia/requisitos-e2-e4.md`.

```
E1 ──► E2 ──► E3 ──► E4
 │             ▲
 └─────────────┘  (E3 puede empezar por la parte de cc con solo E1, pero sus criterios de paridad exigen E2)
```

## E1: núcleo, tablero, adaptador cc y compatibilidad v0

Change: `openspec/changes/orquestador-v1`.

**Qué entra:**
- Proyectos y raíz de estado, carpeta de Cowork aparte y ejecutables por ruta absoluta (cc y git).
- Registro de tareas con su máquina de estados, entrada de Cowork y `orq tarea`.
- Eventos JSONL con redacción, topes y rotación.
- Adaptador `cc` y falso de cc, con la seguridad de cc:
  - perfil y banderas prohibidas;
  - entorno filtrado y worktree sin secretos;
  - auditoría de git y matriz de garantías de cc.
- Planificador: límites, dependencias, un cambio a la vez, worktrees, sesiones, límite de plan, tiempo máximo,
  Job Objects y recuperación al reiniciar.
- Tablero dentro de `orq correr`, con **gate por botón** y sus mitigaciones.
- **Salida de solo lectura para Cowork.**
- Compatibilidad v0: `puente.py` intacto, trabajos v0 en la entrada y `orq importar-v0`.

**Depende de:** nada nuevo. Python 3.12, git y Claude Code ≥ 2.1.302 con sesión iniciada.

**La bloquean:**
- **Decisión 7**: confirmar con el binario real que `claude -p --restricted` funciona con la sesión OAuth de la
  suscripción. Si no, se usa el respaldo `--setting-sources user`.
- **Decisiones 19 a 23**: tablero dentro del orquestador, código en la terminal, carpeta de Cowork aparte,
  `orq tarea` y aviso de integridad. Tienen recomendación; si Sebastian decide otra cosa, cambian specs de E1.
- **Pendiente de Sebastian**: sacar del change la carpeta `specs/paridad-capacidades/`. Es de E3, yo no la pude
  mover y borrar está prohibido por `CLAUDE.md` (ver el resumen de la entrega).

**Criterio de salida:**
- Pruebas sin red con el falso de cc, incluida la de extremo a extremo.
- `openspec validate --strict`.
- Verificación manual de cc hecha por Sebastian.
- Gate por botón probado en el navegador.

## E2: adaptador codex

**Qué entra:**
- Adaptador `codex`:
  - Comando `exec --json` con `-c`, retomar sesión, eventos, límite del plan y consumo.
  - Búsqueda del ejecutable en `%LOCALAPPDATA%\OpenAI\Codex\bin\<hash>\codex.exe`, eligiendo la versión más alta.
  - Falso de codex.
- Seguridad de codex: sandbox `workspace-write` que falla cerrado, `--ignore-user-config`, worktree no confiable
  y `shell_environment_policy` sin secretos.
- Lo que exige dos agentes:
  - Normalización igual de eventos entre cc y codex.
  - `garantia_minima` por proyecto.
  - Traspaso al agotar el plan (decisión 1).
  - Revisión por un agente distinto en modo lectura (decisión 2).
- Campos de tarea `tipo`, `revisa`, `modo` y `traspasos`.

**Depende de:** E1 archivado: núcleo, registro, eventos, tablero, seguridad base y falso.

**La bloquean:**
- Codex instalado y con sesión (`codex login status` con código 0).
- **Decisión 9**: sandbox de Windows. `codex sandbox setup --elevated` como administrador, o comprobar que el
  build permite `mxc` (26200.9278 o mayor; no pude verlo porque me negaron `cmd //c ver`). Además, verificar que
  `-c windows.sandbox=...` falle cerrado.
- Verificación manual de codex: si el `usage` es por turno o acumulado y el código de salida al llegar al límite.

**Criterio de salida:**
- Pruebas con los falsos de cc y codex: normalización igual, traspaso, revisión con otro agente y garantía
  mínima.
- Verificación manual de codex.

## E3: paridad de capacidades y doctor

**Qué entra:**
- Spec `paridad-capacidades` completa:
  - Instrucciones únicas en `AGENTS.md` (con `CLAUDE.md` = `@AGENTS.md`).
  - Skills desde `.agents/skills` y `skills/` global (plugin generado para cc).
  - MCP con lista blanca.
  - Entorno igual (venv y `PATH`).
  - Contrato de entrada y bloque `orq-respuesta` validado.
  - Modelo y esfuerzo por tarea.
  - Elegibilidad por capacidades.
- `orq doctor` y la vista `/paridad` del tablero.
- Calibración opcional `orq calibrar` (decisión 11).
- Adopción de la convención en este repo: `AGENTS.md` como fuente, `CLAUDE.md` con `@AGENTS.md` y las skills de
  OpenSpec como fuente extra (o migradas con `openspec init --tools agents`, si eso genera `.agents/skills`; no
  está verificado).

**Depende de:**
- E1, para la parte de cc.
- **E2**, para los criterios de paridad entre agentes (mismo paquete, mismo entorno, mismos MCP), que necesitan
  al menos dos adaptadores.

**La bloquean:**
- Puntos de la decisión 18 a verificar con los binarios reales:
  - **cc**: `--plugin-dir` y `Skill` junto con `--restricted`.
  - **codex**: si carga skills en `exec`, y si los `-c mcp_servers.*` funcionan con `--ignore-user-config`.
- Lista blanca MCP inicial definida por Sebastian (puede quedar vacía).

**Criterio de salida:**
- Prueba de paridad con los falsos de cc y codex: un proyecto con `AGENTS.md`, una skill y un MCP.
- `doctor` informa bien un agente que falta y uno sin skills.
- Una respuesta sin el formato pedido deja la tarea `fallida`.

## E4: adaptador cursor

**Qué entra:**
- Adaptador `cursor`:
  - Lanzamiento de `%LOCALAPPDATA%\cursor-agent\agent.ps1` por medio de `powershell.exe -NoProfile -NonInteractive
    -File`, o del binario real que envuelva, con el prompt por archivo.
  - `CURSOR_CONFIG_DIR`, eventos, límite heurístico y consumo `null`.
  - Falso de cursor.
- Seguridad de cursor:
  - Revisión de `.cursor/*.json`, `.envrc` y hooks del repo.
  - Revisión de los hooks de usuario (`~/.cursor/hooks.json` y `~/.claude/settings.json`) y de su `mcp.json`.
  - `habilitado: false` hasta la verificación manual (decisión 8).
- Cursor en la normalización de eventos, en la paridad (skills nativas en `.agents/skills`; MCP no elegible hasta
  verificarlo; esfuerzo por slug) y en `doctor` (sesión "desconocida" mientras sus códigos no estén
  documentados).

**Depende de:** E1, E2 (traspaso, revisión, garantía mínima) y E3 (paridad, `doctor`, contrato).

**La bloquean:**
- Cursor instalado y con sesión.
- Verificación manual de cursor (decisiones 8 y 18):
  - Que `-p` sin `--force` no se cuelga y niega.
  - Que el deny aplica en `-p`.
  - Qué cubre `CURSOR_CONFIG_DIR`.
  - Que `session_id` sirve para `--resume`.
  - Si acepta el prompt por stdin.
  - El mensaje del límite del plan.
  - Qué ejecutable envuelve `agent.ps1` y si la política de ejecución de PowerShell exige
    `-ExecutionPolicy Bypass` (es la política de scripts, no un bypass de permisos del agente).
  - Los subtipos de `tool_call`.
  - MCP en `-p`.
  - El shell en Windows.

**Criterio de salida:** pruebas con los tres falsos (normalización y paridad), verificación manual de cursor y
decisión explícita de Sebastian de habilitarlo.

## Pendientes que cruzan etapas

- **Decisión 6** (aislamiento fuerte en Windows): es lo único que cierra los huecos del gate por botón y el riesgo
  de `~/.embudo`. Conviene un change propio, `aislamiento-windows`, después de E1 o en paralelo con E2.
- **Decisión 24** (`~/.embudo`): riesgo abierto por decisión de Sebastian.
- **Migración del proyecto Embudo** al v1: change aparte, cuando Sebastian lo decida.
