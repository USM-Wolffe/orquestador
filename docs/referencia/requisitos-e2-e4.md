# Requisitos de E2, E3 y E4 (referencia)

Estos requisitos y escenarios eran parte del proposal completo `orquestador-v1` (21 y 22-10-2026) y salieron del
change al reducirlo a E1. Quedan aquí textuales, en formato de spec delta, para que el change de cada etapa los
tome. Cuando un requisito de E1 ya existe en `openspec/specs/` (después del archive de E1), el change posterior lo
debe tratar como **MODIFIED**, no como ADDED.

Diseño de referencia: `docs/diseno-orquestador.md`. Etapas: `docs/etapas.md`.

---

## E2: adaptador codex

### Capacidad `adaptadores-agente` (escenarios y requisitos para codex)

#### Scenario: Codex
- **WHEN** se lanza una tarea de `codex`
- **THEN** el comando usa `exec --json`, `--cd <worktree>`, `--sandbox workspace-write` (o `read-only` en modo lectura) y `-` para leer el prompt de la entrada estándar

#### Scenario: Retomar en codex
- **WHEN** hay sesión guardada S para `(proyecto, cambio, codex)`
- **THEN** `codex` usa `exec ... resume S -`; el id S se guardó apenas llegó `thread.started`

#### Scenario: Límite en Codex con apóstrofo tipográfico
- **WHEN** el falso de `codex` emite `turn.failed` con "You’ve hit your usage limit. … Try again at 6:00 PM."
- **THEN** el adaptador informa límite de plan con reinicio a las 18:00 del día que corresponda

#### Scenario: Consumo de Codex
- **WHEN** `codex` emite dos `turn.completed` con `usage`
- **THEN** el consumo suma los tokens de ambos y `costo_usd` es `null`

#### Scenario: Ejecutable de codex con carpeta de versión (nuevo, 22-10-2026)
- **WHEN** existen `%LOCALAPPDATA%\OpenAI\Codex\bin\a1\codex.exe` (0.162.0) y `...\bin\b2\codex.exe` (0.163.0) y la config no fija una ruta absoluta
- **THEN** el orquestador usa `...\bin\b2\codex.exe`, lo registra en `agentes.json` y no consulta el `PATH`

### Capacidad `seguridad-agentes`

#### Scenario: Config de usuario de Codex
- **WHEN** el `config.toml` del usuario de Codex fija `sandbox_mode = "danger-full-access"`
- **THEN** la corrida de `codex` no usa la configuración del usuario y el sandbox queda en el modo que fija el orquestador

#### Scenario: Codex con config de proyecto
- **WHEN** el worktree trae `.codex/config.toml`
- **THEN** `codex` corre igual, porque el orquestador nunca marca el worktree como confiable y Codex no carga esa capa

### Requirement: Garantía mínima por proyecto
Un proyecto SHALL poder fijar `garantia_minima` por control. El orquestador MUST NOT lanzar un agente cuyo nivel
declarado para esa plataforma sea menor; la tarea queda `pendiente` con el motivo y, si ningún agente permitido
cumple, `bloqueada`.

#### Scenario: Proyecto exige sandbox de escritura
- **WHEN** el proyecto exige `sandbox` para escritura y la tarea permite `["cc", "codex"]` en Windows nativo
- **THEN** la tarea solo puede correr con `codex` con su sandbox de Windows activo

### Requirement: Sandbox que falla cerrado
Cuando el perfil de un agente depende de un sandbox del sistema operativo, el adaptador SHALL pedirlo de forma
explícita para que el agente termine con error si el sandbox no está disponible, y MUST NOT caer a una
ejecución sin sandbox.

#### Scenario: Sandbox de Windows de Codex no instalado
- **WHEN** el proyecto exige `sandbox` para escritura y el sandbox de Windows de Codex no está configurado
- **THEN** la corrida de `codex` falla al arrancar, la tarea registra un error de clase `seguridad` y no se ejecuta ningún comando del agente

### Requirement: Revisión en modo lectura
Una tarea `tipo: revision` o `modo: lectura` SHALL correr con el perfil de solo lectura del agente, que además
de las denegaciones obligatorias niega editar y escribir archivos.

#### Scenario: Revisor intenta editar
- **WHEN** el agente de una revisión intenta editar un archivo
- **THEN** la edición se niega y queda un evento `herramienta` con estado `negado`

### Capacidad `eventos-actividad`

### Requirement: Normalización igual para los agentes
Para una misma secuencia de acciones, los adaptadores `cc`, `codex` y `cursor` SHALL producir la misma
secuencia de tipos de evento con los mismos valores en los campos normalizados, salvo `agente`, `sesion`,
`modelo` y las marcas de tiempo.

#### Scenario: Misma corrida en tres agentes
- **WHEN** los ejecutables falsos de los tres agentes emiten el guion "edita `app.py`, corre `py -3.12 -m unittest`, responde y termina con consumo"
- **THEN** las tres secuencias normalizadas son `inicio`, `archivo`, `comando` (en_curso), `comando` (ok), `mensaje`, `fin`, con los mismos `ruta`, `accion`, `comando`, `estado` y `ok`

#### Scenario: Lectura que un agente hace con un comando
- **WHEN** `cc` o `cursor` leen un archivo con su herramienta de lectura y `codex` lo lee con un comando de shell
- **THEN** los dos primeros producen `herramienta` con `nombre: "leer"` y `codex` produce `comando`, sin contenido leído en ninguno

(En E2 se prueba con `cc` y `codex`; E4 agrega `cursor`.)

### Capacidad `planificacion-ejecucion`

#### Scenario: Otro agente en el mismo cambio
- **WHEN** arranca T-3 de `codex` en el cambio `login`
- **THEN** el comando no retoma la sesión de `cc` y empieza una sesión de `codex`

### Requirement: Traspaso a otro agente
Si un proyecto tiene `traspaso: "auto"` y una tarea se detiene por límite de plan con espera mayor a
`traspaso_si_espera_min`, el orquestador SHALL reasignarla a otro agente de `agentes_permitidos` que esté
disponible y no esté excluido, una sola vez por tarea. Con `traspaso: "manual"` MUST esperar o dejar que Cowork
cambie el agente.

#### Scenario: Traspaso automático
- **WHEN** el proyecto tiene `traspaso: "auto"`, T-5 permite `["cc", "codex"]`, `cc` se agota por 3 horas y `codex` está disponible
- **THEN** T-5 queda con `agente: "codex"`, un evento `error` de clase `limite_uso` y una entrada de historial "traspaso cc→codex", y su prompt incluye el aviso de traspaso y el `diff --stat` del worktree

#### Scenario: Traspaso manual
- **WHEN** el proyecto tiene `traspaso: "manual"`
- **THEN** T-5 espera a `cc` hasta `no_antes_de` y el tablero muestra que hay otro agente permitido disponible

### Requirement: Revisión por un agente distinto
Una tarea con `tipo: "revision"` y `revisa: <id>` SHALL correr con un agente distinto del que ejecutó la tarea
revisada, en modo de solo lectura. Si ningún agente permitido cumple, MUST quedar `bloqueada` con ese motivo.

#### Scenario: Revisor distinto
- **WHEN** T-7 la ejecutó `cc` y R-7 (`tipo: revision`, `revisa: T-7`) permite `["cc", "codex"]`
- **THEN** R-7 corre con `codex` en modo lectura

#### Scenario: Sin revisor posible
- **WHEN** R-7 solo permite `["cc"]` y T-7 la ejecutó `cc`
- **THEN** R-7 queda `bloqueada` con el motivo "no hay agente revisor distinto del implementador"

### Capacidad `registro-tareas` (campos de E2)

Campos opcionales que se suman a la tarea: `tipo` (`implementacion|revision`), `revisa`, `modo`
(`escritura|lectura`) y `traspasos`. La transición `pendiente`→`bloqueada` también aplica cuando no hay agente
apto (garantía mínima o revisor distinto).

---

## E3: paridad de capacidades y doctor

### Capacidad `paridad-capacidades` (spec completa)

## Purpose

Asegura que Claude Code, Codex y Cursor trabajen con el mismo contexto y las mismas capacidades, de modo que el
resultado de una tarea dependa de la tarea y no del agente que la tome.

### Requirement: Fuente única de instrucciones del proyecto
Las instrucciones de cada proyecto SHALL vivir en un solo `AGENTS.md` en la raíz del repo. Un `CLAUDE.md` en la
raíz MUST contener solo la importación `@AGENTS.md` y comentarios; si no existe, el orquestador lo genera en el
worktree, excluido de git. El orquestador MUST NOT lanzar una tarea si esto no se cumple.

#### Scenario: CLAUDE.md con contenido propio
- **WHEN** el `CLAUDE.md` del worktree trae reglas además de `@AGENTS.md`
- **THEN** la tarea no se lanza, queda con error de clase `paridad` que nombra `CLAUDE.md`, y `doctor` lo informa como "instrucciones divergentes"

#### Scenario: Proyecto sin CLAUDE.md
- **WHEN** el repo tiene `AGENTS.md` y no tiene `CLAUDE.md`
- **THEN** el orquestador escribe en el worktree un `CLAUDE.md` con `@AGENTS.md`, lo agrega a la exclusión de git y lanza la tarea

#### Scenario: Proyecto sin AGENTS.md
- **WHEN** el repo no tiene `AGENTS.md`
- **THEN** ninguna tarea del proyecto se lanza y el motivo pide crear `AGENTS.md`

### Requirement: Tope de tamaño de las instrucciones
`AGENTS.md` MUST medir como máximo 32 KiB, el menor tope documentado entre los tres agentes, para que ninguno lo
lea truncado. Los `AGENTS.md` o `CLAUDE.md` en subcarpetas SHALL informarse como advertencia en `doctor`, porque
no todos los agentes los cargan igual.

#### Scenario: AGENTS.md muy grande
- **WHEN** `AGENTS.md` mide 40 KiB
- **THEN** ninguna tarea se lanza y el motivo indica el tope de 32 KiB

#### Scenario: AGENTS.md anidado
- **WHEN** existe `src/AGENTS.md`
- **THEN** las tareas se lanzan y `doctor` muestra la advertencia con la ruta

#### Scenario: Instrucciones personales de un agente
- **WHEN** existe `~/.claude/CLAUDE.md`, un `AGENTS.md` en la carpeta de Codex o reglas de usuario de Cursor
- **THEN** `doctor` informa la ruta y el tamaño, sin leer el contenido, como "instrucciones que solo ve un agente"

### Requirement: Fuente única de skills y publicación por agente
Las skills de un proyecto SHALL vivir en `.agents/skills/<nombre>/SKILL.md`, más las fuentes extra que declare
`proyecto.json`, y las globales en `skills/` de la instalación. Antes de cada corrida, el orquestador MUST dejar
el mismo conjunto visible por la vía nativa de cada agente (una ruta que lee o un plugin generado), con copias
marcadas y excluidas de git, sin sobrescribir archivos versionados.

#### Scenario: Skill de proyecto en los tres agentes
- **WHEN** el proyecto tiene `.agents/skills/revisar-sql/SKILL.md`
- **THEN** tras preparar la corrida, el falso de cada agente encuentra `revisar-sql` por su vía nativa, y cada copia generada trae el archivo marcador `.orq-generado`

#### Scenario: Carpeta de skills de un solo agente
- **WHEN** el repo trae `.codex/skills/x` o `.cursor/skills/x` y el proyecto no declaró esa carpeta como fuente
- **THEN** la preparación falla con error de clase `paridad`, porque solo algunos agentes verían esa skill

#### Scenario: Sin skills repetidas
- **WHEN** un agente lee varias rutas de skills (por ejemplo `cursor` lee `.agents/skills` y `.claude/skills`)
- **THEN** la publicación no le deja dos copias de la misma skill, salvo en el respaldo documentado, y `doctor` informa cualquier repetición

#### Scenario: Conflicto de nombre
- **WHEN** existe una skill versionada `x` en la ruta nativa de un agente con contenido distinto de la skill `x` de la fuente
- **THEN** la tarea no se lanza y queda con error de clase `paridad` que nombra las dos rutas

#### Scenario: Copia generada alterada
- **WHEN** una copia generada fue modificada después de la corrida anterior
- **THEN** el orquestador la reemplaza por la versión de la fuente antes de lanzar y lo deja en el registro

### Requirement: Frontmatter portable de las skills
Toda skill MUST tener `name` en minúsculas con guiones, de máximo 64 caracteres e igual al nombre de su carpeta,
y `description` no vacía de máximo 1.024 caracteres. Las copias generadas SHALL llevar solo `name`,
`description`, `license`, `compatibility` y `metadata`; los demás campos se quitan y `doctor` los informa.

#### Scenario: Skill con campos propios de un agente
- **WHEN** una skill de la fuente trae `allowed-tools` y `hooks`
- **THEN** las copias generadas no tienen esos campos y `doctor` muestra la advertencia "campo no portable"

#### Scenario: Nombre inválido
- **WHEN** una skill tiene `name: Revisar_SQL` o un nombre distinto de su carpeta
- **THEN** la preparación falla con error de clase `paridad` y la tarea no se lanza

### Requirement: Skills dentro del paquete de entrada
El paquete de entrada SHALL incluir, igual para todos los agentes, el índice de skills visibles (nombre,
descripción y ruta en el worktree) y el contenido completo de cada skill nombrada en `contrato.skills`, de modo
que un agente que no carga skills sin ventana reciba lo mismo que los demás.

#### Scenario: Tarea que pide una skill
- **WHEN** una tarea trae `contrato.skills: ["revisar-sql"]`
- **THEN** el paquete de los tres agentes trae el texto completo de `revisar-sql/SKILL.md`

### Requirement: Servidores MCP declarados una vez
Los servidores MCP SHALL declararse solo en la lista blanca de la configuración global, habilitarse por proyecto
y elegirse por tarea. En cada corrida el orquestador MUST generar la configuración MCP de cada agente solo con
esos servidores y MUST anular toda otra fuente (repo y usuario). Un servidor con `red: true` solo se habilita si
la tarea tiene red.

#### Scenario: MCP declarado
- **WHEN** la tarea pide el servidor `docs-locales`, que está en la lista blanca y habilitado en el proyecto
- **THEN** cada adaptador recibe una configuración generada con exactamente ese servidor, el mismo comando y los mismos argumentos

#### Scenario: Servidor fuera de la lista blanca
- **WHEN** una solicitud pide el servidor `cualquiera`, que no está en la lista blanca
- **THEN** la solicitud se rechaza

#### Scenario: MCP del repo
- **WHEN** el worktree trae `.mcp.json`, `.cursor/mcp.json` o `.codex/config.toml` con servidores
- **THEN** ningún agente carga esos servidores en la corrida

#### Scenario: Fuente que no se puede anular
- **WHEN** un agente no permite anular los servidores MCP del usuario (por ejemplo `cursor` con `~/.cursor/mcp.json` no vacío)
- **THEN** ese agente no se lanza y `doctor` informa el archivo, sin mostrar su contenido

#### Scenario: Servidor con red en tarea sin red
- **WHEN** la tarea pide un servidor marcado `red: true` y la tarea no tiene red
- **THEN** la solicitud se rechaza con ese motivo

### Requirement: Elegibilidad por capacidades
Un agente MUST NOT tomar una tarea si no puede darle una capacidad que la tarea pide (servidores MCP, modelo o
esfuerzo), según la matriz de capacidades del orquestador y el último `doctor`. Si ningún agente permitido
puede, la tarea queda `bloqueada` con el motivo.

#### Scenario: Agente sin MCP sin ventana
- **WHEN** la tarea pide un servidor MCP y la matriz dice que `cursor` no puede usarlo sin ventana
- **THEN** `cursor` no es elegible para esa tarea, aunque esté en `agentes_permitidos`

### Requirement: Entorno igual para los tres agentes
Para una misma tarea, los tres agentes SHALL recibir la misma carpeta de trabajo (el worktree), el mismo `PATH`
(con el `Scripts` del venv del proyecto primero), el mismo `VIRTUAL_ENV` y las mismas variables del proyecto.
Solo MUST diferir las variables propias de cada adaptador, que están en una lista fija.

#### Scenario: Tres agentes falsos
- **WHEN** la misma tarea corre con el falso de `cc`, el de `codex` y el de `cursor`
- **THEN** las tres trazas tienen la misma carpeta de trabajo, el mismo `PATH` y el mismo `VIRTUAL_ENV`, y las variables que difieren están en la lista de variables propias del adaptador

#### Scenario: Herramienta que falta
- **WHEN** `entorno.herramientas` incluye `pytest` y no se encuentra con el `PATH` de la corrida
- **THEN** la tarea no se lanza, queda `pendiente` con el motivo y `doctor` lo informa

### Requirement: Paquete de entrada común
Toda tarea v1 SHALL traer `contrato` con `objetivo`, al menos un criterio de aceptación y, si aplica, `archivos`,
`pruebas_esperadas`, `no_tocar` y `skills`. El orquestador MUST armar con eso un único texto de entrada, idéntico
byte a byte para cualquier agente, con las instrucciones globales del orquestador y el formato de respuesta.

#### Scenario: Mismo paquete para los tres
- **WHEN** un proyecto con `AGENTS.md`, una skill y un servidor MCP declarados corre la misma tarea con los tres agentes falsos
- **THEN** los tres reciben exactamente el mismo texto de entrada, cada adaptador recibió la configuración de skills y MCP que su agente necesita, y las tres configuraciones declaran la misma skill y el mismo servidor

#### Scenario: Contrato incompleto
- **WHEN** una solicitud `crear` trae `contrato` sin `criterios_aceptacion`
- **THEN** la solicitud se rechaza

#### Scenario: Paquete demasiado grande
- **WHEN** el paquete armado, con las skills pedidas completas, supera 64 KiB
- **THEN** la solicitud se rechaza y el acuse pide reducir las skills pedidas

### Requirement: Formato de respuesta validado
La respuesta final SHALL terminar con un bloque de código `orq-respuesta` con un JSON de claves `resumen`, `pruebas`,
`tareas_abiertas` y `permisos_negados`. Si el bloque falta, no es JSON, le faltan claves, los tipos no calzan o
no informa cada prueba esperada, la tarea MUST pasar a `fallida` con clase `formato_respuesta` y el motivo.

#### Scenario: Respuesta sin el bloque
- **WHEN** el agente falso termina bien pero su texto final no trae el bloque `orq-respuesta`
- **THEN** la tarea pasa a `fallida` con clase `formato_respuesta` y el motivo "falta el bloque orq-respuesta"

#### Scenario: Prueba esperada sin informar
- **WHEN** el contrato pide la prueba `py -3.12 -m unittest pruebas.test_login` y la respuesta no la incluye en `pruebas`
- **THEN** la tarea pasa a `fallida` con un motivo que nombra esa prueba

#### Scenario: Respuesta válida
- **WHEN** la respuesta trae el bloque completo y bien formado
- **THEN** el JSON queda en `resultado.respuesta` y la tarea sigue su curso normal

#### Scenario: Trabajo v0
- **WHEN** la tarea vino en formato v0 y quedó con `contrato.respuesta: "libre"`
- **THEN** la respuesta no se valida contra el formato

### Requirement: Cumplimiento del contrato
Con una respuesta válida, si alguna prueba esperada no figura como `paso`, la tarea SHALL ir a `esperando_gate`
aunque no pida gate. Si el diff del intento toca una ruta de `no_tocar`, la tarea MUST pasar a `fallida` con clase
`contrato` y la lista de rutas. Las negaciones de permisos que se observaron y que la respuesta omite se marcan
como advertencia.

#### Scenario: Prueba que falló
- **WHEN** la respuesta informa `"resultado": "fallo"` para una prueba esperada en una tarea sin gate
- **THEN** la tarea pasa a `esperando_gate` con el motivo "pruebas esperadas sin pasar"

#### Scenario: Archivo protegido modificado
- **WHEN** `no_tocar` incluye `puente.py` y el intento lo modificó
- **THEN** la tarea pasa a `fallida` con clase `contrato` y la ruta `puente.py`

### Requirement: Modelo y esfuerzo por tarea
Una tarea SHALL poder pedir `modelo` y `esfuerzo`, como valor común o por agente; lo que no pida sale de
`modelos` en `proyecto.json`. El adaptador MUST traducirlo a los flags verificados de su agente, rechazar los
valores que ese agente no acepta y guardar en cada corrida lo pedido y el modelo efectivo que informe el agente.

#### Scenario: Esfuerzo común
- **WHEN** una tarea pide `esfuerzo: "alto"` y el proyecto traduce `alto` a `high` para `cc` y `codex`
- **THEN** el comando de `cc` lleva `--effort high`, el de `codex` lleva `-c model_reasoning_effort="high"`, el de `cursor` lleva en `--model` el slug que el proyecto asocia a `alto`, y la corrida guarda lo pedido

#### Scenario: Esfuerzo sin traducción
- **WHEN** la tarea pide `esfuerzo: "alto"` y el proyecto no tiene traducción de `alto` para `cursor`
- **THEN** `cursor` no es elegible para esa tarea y el motivo lo dice

#### Scenario: Valor no aceptado
- **WHEN** una tarea pide `esfuerzo: {"cc": "turbo"}`
- **THEN** la solicitud se rechaza porque `turbo` no está entre los valores de `cc`

#### Scenario: Modelo efectivo
- **WHEN** el evento de inicio del agente informa el modelo `claude-opus-5-5`
- **THEN** la corrida guarda `modelo_efectivo: "claude-opus-5-5"`; si el agente no lo informa, guarda `no informado`

### Requirement: Comando doctor
`orq doctor` SHALL revisar en cada agente configurado: instalado y versión; sesión iniciada, solo por el código de
salida de su comando de estado (sin leer credenciales ni guardar su salida); instrucciones, skills y MCP del
proyecto visibles por su vía nativa; y herramientas del entorno. MUST imprimir una tabla y dejar el resultado en
`doctor.json`.

#### Scenario: Agente que falta
- **WHEN** el ejecutable de `codex` no existe
- **THEN** la fila de `codex` dice "no instalado" en todas sus columnas, las demás filas se revisan igual y el comando termina sin error

#### Scenario: Agente sin skills
- **WHEN** el proyecto tiene una skill y la matriz dice que un agente no carga skills sin ventana
- **THEN** su fila dice "sin skills nativas (van en el paquete)" en la columna de skills

#### Scenario: Sin comando de estado
- **WHEN** un agente no tiene un comando de estado de sesión verificado
- **THEN** la columna de sesión dice "desconocida", no "sí"

#### Scenario: No lee credenciales
- **WHEN** corre `orq doctor` con archivos de credenciales sintéticos en las carpetas de configuración de los tres agentes
- **THEN** el proceso de `orq doctor` no abre esos archivos, según un hook de auditoría de Python (`sys.addaudithook`), y la salida de los comandos de estado no queda guardada en ningún lado

### Capacidad `tablero` (agregado de E3)

### Requirement: Vista de paridad
El tablero SHALL tener una vista que muestre el último `doctor.json`: una fila por agente con instalado y versión,
sesión, instrucciones, skills, MCP, herramientas del entorno, advertencias y la hora de la revisión. El detalle de
cada tarea MUST mostrar el modelo y el esfuerzo pedidos, el modelo efectivo y el resultado de validar la respuesta.

#### Scenario: Doctor con un agente que falta
- **WHEN** `doctor.json` dice que `codex` no está instalado
- **THEN** la vista de paridad muestra la fila de `codex` como "no instalado" y las demás filas con sus datos

#### Scenario: Doctor viejo
- **WHEN** el último `doctor.json` tiene más de 24 horas
- **THEN** la vista lo marca como desactualizado y muestra cómo correr `orq doctor`

#### Scenario: Respuesta que no cumplió el formato
- **WHEN** Sebastian abre una tarea `fallida` por `formato_respuesta`
- **THEN** el detalle muestra la lista de problemas encontrados en la respuesta

### Capacidad `registro-tareas` y `compatibilidad-v0` (cambios de E3)

- `contrato` pasa a ser campo mínimo de las tareas v1 (y `prompt` queda como texto adicional). Se suman los
  opcionales `modelo`, `esfuerzo` y `mcp`.
- Escenario modificado de `compatibilidad-v0`: un trabajo v0 convertido queda con `contrato.objetivo` igual al
  prompt y `contrato.respuesta: "libre"`.
- Escenario modificado de `adaptadores-agente`: el resultado incluye el modelo efectivo.

---

## E4: adaptador cursor

### Capacidad `adaptadores-agente` (escenarios para cursor)

#### Scenario: Cursor
- **WHEN** se lanza una tarea de `cursor`
- **THEN** el comando usa `-p`, `--output-format stream-json`, `--workspace <worktree>` y `--trust`, sin `--force`, y la entrada estándar queda cerrada si el prompt no va por ahí

#### Scenario: Ejecutable .cmd o .ps1
- **WHEN** el ejecutable resuelto termina en `.cmd`, `.bat` o `.ps1` y el adaptador necesitaría poner el prompt como argumento
- **THEN** el adaptador escribe el prompt en un archivo dentro de `.orq\` del worktree (excluido de git) y el argumento solo nombra ese archivo

#### Scenario: Ejecutable de cursor (nuevo, 22-10-2026)
- **WHEN** la config apunta `cursor` a `%LOCALAPPDATA%\cursor-agent\agent.ps1`
- **THEN** el orquestador lo lanza con la ruta absoluta de `powershell.exe -NoProfile -NonInteractive -File`, sin consultar el `PATH`, y ningún texto libre de la tarea va en los argumentos

#### Scenario: Retomar en cursor
- **WHEN** hay sesión guardada S para `(proyecto, cambio, cursor)`
- **THEN** `cursor` usa `--resume S`; S se guardó desde `system/init`

#### Scenario: Límite en Cursor sin hora
- **WHEN** el falso de `cursor` termina con código distinto de cero, sin evento `result` y con "usage limit" en la salida de error
- **THEN** el adaptador informa límite de plan sin hora de reinicio

#### Scenario: Consumo de Cursor
- **WHEN** `cursor` termina con `result` sin datos de uso
- **THEN** todos los campos de tokens y costo son `null` y la duración sale de `duration_ms`

### Capacidad `seguridad-agentes` (cursor)

#### Scenario: Hooks de usuario que Cursor importa
- **WHEN** `~/.cursor/hooks.json` o `~/.claude/settings.json` (que Cursor importa) tienen hooks cuya huella no está aprobada en la configuración global
- **THEN** la tarea de `cursor` no se lanza y queda con error de clase `seguridad` que nombra el archivo, sin mostrar su contenido

#### Scenario: Hook desconocido en el repo
- **WHEN** el worktree trae `.cursor/hooks.json` y su huella SHA-256 no está aprobada en `proyecto.json`
- **THEN** la tarea de `cursor` no se lanza y queda con error de clase `seguridad` que nombra el archivo

(La revisión de configuración del repo para `cursor` cubre `.cursor/*.json`, `.envrc` y los hooks de
`.claude/settings*.json`.)

### Requirement: Agentes que requieren verificación manual
Un agente cuyo comportamiento de seguridad no está confirmado con el binario real SHALL venir deshabilitado en la
configuración global, y MUST quedar no disponible hasta que Sebastian lo habilite de forma explícita después de
correr la lista de verificación manual.

#### Scenario: Cursor sin verificar
- **WHEN** la configuración global no tiene `agentes.cursor.habilitado: true`
- **THEN** las tareas de `cursor` esperan con el motivo "agente sin verificación manual" y Cowork lo ve en el acuse
