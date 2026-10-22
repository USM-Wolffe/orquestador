# Spec Delta

## Purpose

Asegura que el puente v0 y sus trabajos sigan funcionando mientras existan, y da un camino claro y de solo
lectura para pasar un proyecto del v0 al orquestador v1.

## ADDED Requirements

### Requirement: El puente v0 sigue igual
`puente.py` SHALL seguir aceptando el formato de trabajo v0 (`id`, `tipo`, `cambio`, `rama`, `base`, `prompt`,
`nueva_sesion`, `timeout_min`, `acciones`, `mensaje`, `no_antes_de`, `reintentos`, `repo`), la misma
`config.json`, las mismas carpetas y las mismas salidas (`hechos\<id>.md`, `<id>.resultado.json`,
`<id>.trabajo.json`, `sesiones.json`, `estado.json`, `registro.log`).

#### Scenario: Trabajo v0 con Claude Code falso
- **WHEN** se corre `puente.py --una-vez` con un trabajo `tipo: cc` en `trabajos\pendientes\` y `claude` apuntando al ejecutable falso
- **THEN** quedan `trabajos\hechos\<id>.md` con la respuesta, `<id>.resultado.json` con `codigo`, `session_id` y `total_cost_usd`, y `sesiones.json` con la sesión del cambio

#### Scenario: Límite de plan en v0
- **WHEN** el ejecutable falso responde con el límite de uso
- **THEN** el trabajo vuelve a `trabajos\pendientes\` con `reintentos: 1` y `no_antes_de` 30 minutos después, como hoy

### Requirement: Trabajos v0 en la entrada del v1
El orquestador SHALL aceptar en la entrada de Cowork un trabajo v0 de `tipo: cc` (un objeto sin `op` y con
`tipo`) y convertirlo en una tarea con `agente` y `agentes_permitidos` = `cc`, sin gate, con los mismos `id`,
`cambio`, `rama`, `prompt`, `nueva_sesion`, `timeout_min` y `no_antes_de`, y la rama base del trabajo si la trae.

#### Scenario: Trabajo v0 convertido
- **WHEN** Cowork deja en la entrada `{"id": "t1", "tipo": "cc", "cambio": "login", "prompt": "..."}`
- **THEN** el registro tiene la tarea `t1` con `agente: "cc"`, `cambio: "login"`, el mismo `prompt` y estado `pendiente`, y el acuse dice que vino en formato v0

#### Scenario: Trabajo v0 corre en el v1
- **WHEN** esa tarea arranca
- **THEN** corre con el adaptador `cc` en `wt-login` y termina con el texto en `salida\resultados\t1.md` de la carpeta de Cowork

### Requirement: Acciones de git del v0 no pasan al v1
Un trabajo v0 con `tipo: git` o con el campo `repo` MUST rechazarse en la entrada del v1 con un acuse que explique
el motivo: los commits, archive y merge los hace Sebastian, y en el v1 cada repo es un proyecto.

#### Scenario: Trabajo de commit
- **WHEN** llega un trabajo v0 `{"tipo": "git", "acciones": ["commit"], ...}`
- **THEN** el acuse dice `ok: false` con el motivo y no se crea ninguna tarea

### Requirement: Importación del estado v0 sin tocar el origen
El comando `orq importar-v0 --desde <carpeta v0> --proyecto <p>` SHALL leer `sesiones.json` y los trabajos de
`trabajos\pendientes\` y mostrar lo que importaría; solo con `--aplicar` MUST crear las sesiones `(p, cambio,
cc)` y las tareas. Nunca MUST escribir, mover ni borrar nada en la carpeta de origen.

#### Scenario: Simulación
- **WHEN** se corre sin `--aplicar`
- **THEN** imprime las sesiones y tareas que importaría y no escribe en ningún lado

#### Scenario: Importación aplicada
- **WHEN** se corre con `--aplicar` sobre una copia sintética de una carpeta v0
- **THEN** el proyecto queda con las sesiones y tareas importadas, y la carpeta de origen tiene exactamente los mismos archivos, contenidos y fechas que antes

#### Scenario: Sesión importada se retoma
- **WHEN** después de importar arranca una tarea `cc` del cambio `login` que tenía sesión en el v0
- **THEN** el comando retoma esa sesión
