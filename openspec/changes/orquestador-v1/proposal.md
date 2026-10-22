# Proposal

## Why

El puente v0 (`puente.py`) demostró que Cowork puede entregarle trabajo a Claude Code sin ventana y con permisos
fijos, pero corre un trabajo a la vez, no lleva un registro de tareas y no deja ver qué hace el agente. Sebastian
aprobó el 22-10-2026 el diseño completo del orquestador como referencia (`docs/diseno-orquestador.md`) y lo
divide en cuatro etapas (`docs/etapas.md`). Este change es **E1**: el núcleo con el adaptador de Claude Code, el
tablero con gates por botón, la lectura del estado por Cowork y la compatibilidad con el v0.

## What Changes

- **Proyectos**: una instalación atiende varios repos. El estado de cada proyecto queda en
  `%USERPROFILE%\.orquestador\proyectos\<p>\`, fuera del repo. Los ejecutables (`claude` y `git`) se lanzan desde
  rutas absolutas de la config, nunca desde el `PATH`.
- **Registro de tareas** en JSON por proyecto, con un solo escritor y una máquina de estados (pendiente,
  bloqueada, en_curso, esperando_gate, hecha, fallida, cancelada). Cowork pide cambios en una carpeta de entrada.
- **Eventos** JSONL normalizados, sin contenido de archivos ni secretos, con tope y rotación.
- **Adaptador `cc`** (`claude -p --output-format stream-json --permission-mode dontAsk --restricted`) con su
  perfil de permisos, retomar sesión, límite del plan, consumo y un ejecutable falso para pruebas.
- **Seguridad de cc**:
  - Revisión de banderas prohibidas, entorno filtrado, worktree sin secretos y skills que conceden permisos.
  - Auditoría de git antes y después de cada corrida, y nivel de garantía declarado por control.
- **Planificador**: límite global y por agente, dependencias, un cambio a la vez (también mientras espera gate),
  un worktree por cambio, tiempo máximo, Job Objects y recuperación al reiniciar.
- **Tablero** dentro de `orq correr`, solo en `127.0.0.1`, con enlace de entrada de un solo uso y sesión en
  memoria: kanban, detalle en vivo, consumo y `diff --stat` (con archivos nuevos).
- **Gate por botón** (decisión de Sebastian): aprobar o rechazar con nota desde el tablero, con dos pasos, un
  código que solo aparece en la terminal, la huella del estado revisado, CSRF y origen, bloqueo por códigos
  erróneos, registro y aviso de integridad del código. **BREAKING** respecto del proposal anterior: desaparece
  `orq gate` y el tablero deja de ser solo de lectura para esa acción.
- **Lectura del estado por Cowork**: carpeta propia `%USERPROFILE%\Orquestador-Cowork\<p>\` (entrada, respuestas
  y una `salida\` de solo lectura con estado, eventos recientes, resultados, diff stat y consumo), sin secretos.
- **Compatibilidad v0**: `puente.py` intacto con pruebas de regresión, trabajos v0 de tipo `cc` en la entrada e
  `orq importar-v0` en modo simulación por defecto.
- **Fuera de este change** (en la referencia): adaptadores codex (E2) y cursor (E4), traspaso, revisión por otro
  agente, garantía mínima, paridad de capacidades, contrato de respuesta y `doctor` (E3).

## Capabilities

### New Capabilities
- `proyectos`: registro de proyectos, configuración por proyecto y raíz de estado.
- `registro-tareas`: modelo de tarea, máquina de estados, actores de cada transición y entrada de Cowork.
- `eventos-actividad`: registro JSONL normalizado, redacción, topes y rotación.
- `adaptadores-agente`: interfaz común, ejecutables por ruta absoluta y adaptador `cc`.
- `seguridad-agentes`: controles obligatorios de cc, niveles de garantía, revisiones previas y auditoría de git.
- `planificacion-ejecucion`: paralelismo, dependencias, exclusión por cambio, worktrees, límite de plan, tiempos y reinicio.
- `tablero`: tablero local dentro del orquestador, protegido, de solo lectura salvo los gates.
- `aprobacion-gates`: decisión de gates por botón y sus defensas.
- `estado-cowork`: carpeta de Cowork y salida de solo lectura sin secretos.
- `compatibilidad-v0`: continuidad del v0 e importación de su estado.

### Modified Capabilities
- Ninguna: el repo no tenía specs antes de este change.

## Impact

- **Código nuevo**: paquete `orquestador/` y `orq.py`; pruebas en `pruebas/` con el ejecutable falso de cc.
  `puente.py` no cambia.
- **Dependencias**: solo librería estándar de Python 3.12 (`ctypes` para Job Objects).
- **Sistemas**:
  - Crea `%USERPROFILE%\.orquestador\` y `%USERPROFILE%\Orquestador-Cowork\`, y worktrees `wt-<cambio>` junto a
    cada repo.
  - Escucha en `127.0.0.1` mientras corre `orq correr`.
- **Agentes**: requiere Claude Code 2.1.302 o posterior con sesión iniciada. Codex y Cursor no se usan en E1.
- **No toca** `C:\work\Embudo de Riesgo\` ni su orquestador v0.
- **Pendiente de Sebastian**: la carpeta `specs/paridad-capacidades/` sigue en este change porque no pude
  moverla (me negaron `mv` y `cp`) y `CLAUDE.md` prohíbe borrar fuera de `out/`. Es de E3 y su contenido ya está en
  `docs/referencia/requisitos-e2-e4.md`. Hay que borrarla antes del apply.
