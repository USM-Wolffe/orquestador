# adaptadores-agente Specification

## Purpose
Define la interfaz común con la que el orquestador lanza y lee a los agentes de código, y su primera
implementación, el adaptador de Claude Code (`cc`), para que el resto del sistema no dependa de qué agente ejecuta
una tarea.

## Requirements

### Requirement: Interfaz común de adaptador
Cada adaptador SHALL entregar: el comando de lanzamiento (argumentos, entorno, carpeta y texto de entrada), la
traducción de cada línea de su salida a eventos normalizados, la detección del límite de uso del plan, y la
lectura del id de sesión, del resultado final y del consumo. El resto del orquestador MUST usar solo esa interfaz.

#### Scenario: Ciclo común
- **WHEN** el planificador corre una tarea de `cc`
- **THEN** pasa por el ciclo genérico de lanzar, leer eventos, detectar límite y cerrar con resultado y consumo, sin código propio de `cc` fuera del adaptador

#### Scenario: Adaptador de prueba
- **WHEN** las pruebas registran un adaptador mínimo distinto de `cc`
- **THEN** el planificador lo corre con el mismo ciclo, sin cambios en el núcleo

### Requirement: Ejecutable por ruta absoluta, sin PATH
El ejecutable de cada agente SHALL venir de `config.json` como ruta absoluta (o lista cuyo primer elemento es una
ruta absoluta), y el orquestador MUST lanzarlo con esa ruta sin buscarlo en el `PATH`. Si la ruta no es absoluta
o no existe, el agente queda no disponible con ese motivo.

#### Scenario: Ruta absoluta válida
- **WHEN** `agentes.cc.ejecutable` es `C:\Users\<usuario>\.local\bin\claude.exe` y el archivo existe
- **THEN** el comando lanzado empieza con esa ruta exacta

#### Scenario: Nombre suelto
- **WHEN** `agentes.cc.ejecutable` es `claude`, sin ruta
- **THEN** `cc` queda no disponible con el motivo "el ejecutable debe ser una ruta absoluta" y no se consulta el `PATH`

#### Scenario: PATH engañoso
- **WHEN** el `PATH` del orquestador tiene primero una carpeta con un `claude.exe` falso y la config apunta al verdadero
- **THEN** se lanza el de la config

#### Scenario: Ejecutable falso para pruebas
- **WHEN** la configuración apunta `cc` a `[<ruta absoluta de python.exe>, <ruta de agente_falso.py>, --como, cc]`
- **THEN** el orquestador lo usa igual que al ejecutable real

### Requirement: Versión verificada
Al iniciar, el orquestador SHALL leer la versión de cada agente habilitado con `--version` (tiempo máximo 10 s) y
marcarlo no disponible si no responde o si es anterior a la mínima verificada (2.1.302 para `cc`). Una versión
mayor que la verificada MUST quedar marcada "no verificada".

#### Scenario: Versión antigua
- **WHEN** el ejecutable de `cc` informa 2.1.250
- **THEN** `cc` queda no disponible, sus tareas esperan en `pendiente` con ese motivo y Cowork lo ve en su salida

#### Scenario: Versión más nueva
- **WHEN** la versión instalada es mayor que la verificada
- **THEN** el agente queda disponible y cada evento `inicio` trae la advertencia "versión no verificada"

### Requirement: Lanzamiento de Claude Code sin ventana
El adaptador `cc` SHALL lanzar `claude` con `-p`, `--output-format stream-json`, `--verbose`, `--permission-mode
dontAsk`, `--permission-prompts none`, `--restricted`, `--tools` con la lista del perfil, `--settings` con el
perfil generado, `--strict-mcp-config` y `--disallowedTools "mcp__*"`, con `ENABLE_CLAUDEAI_MCP_SERVERS=false` en
el entorno, la carpeta de trabajo en el worktree y el prompt solo por la entrada estándar. El perfil SHALL llevar
`disableClaudeAiConnectors: true` y `"mcp__*"` en `permissions.deny`.

#### Scenario: Comando de cc
- **WHEN** se lanza una tarea de `cc`
- **THEN** el comando trae esas banderas, el prompt no aparece en los argumentos y el proceso corre sin ventana

#### Scenario: Respaldo sin restricted
- **WHEN** la config global tiene `agentes.cc.restricted: false` (decisión 7)
- **THEN** el comando usa `--setting-sources user` en lugar de `--restricted` y el perfil lleva `disableAllHooks: true`

#### Scenario: Perfil sin conectores
- **WHEN** se genera el perfil de `cc`, con `--restricted` o con el respaldo
- **THEN** el perfil lleva `disableClaudeAiConnectors: true` y `"mcp__*"` en `permissions.deny`

### Requirement: Retomar la sesión del cambio
El adaptador `cc` SHALL abrir sesiones nuevas con `--session-id <uuid>` generado y guardado por el orquestador
antes de lanzar, y retomar con `--resume <uuid>`. Solo MUST pasar ids que cumplen el formato UUID.

#### Scenario: Retomar
- **WHEN** hay sesión guardada S para `(proyecto, cambio, cc)`
- **THEN** el comando usa `--resume S`

#### Scenario: Sesión que ya no existe
- **WHEN** Claude Code responde que la sesión S no existe
- **THEN** el orquestador borra S del registro de sesiones, reintenta una vez con sesión nueva y lo deja en el historial

### Requirement: Detección del límite de uso del plan
El adaptador `cc` SHALL reconocer el límite de uso del plan por `rate_limit_event` con `status: "rejected"`, por
`assistant.error: "rate_limit"` o por los textos de límite que reconoce el v0 y la documentación, y entregar la
hora de reinicio cuando venga (`resetsAt`).

#### Scenario: Límite con hora
- **WHEN** el falso de `cc` emite `rate_limit_event` con `status: "rejected"` y `resetsAt`
- **THEN** el adaptador informa límite de plan con esa hora de reinicio

#### Scenario: Límite solo por texto
- **WHEN** el resultado trae `is_error: true` y "You've hit your session limit · resets 3:45pm"
- **THEN** el adaptador informa límite de plan con reinicio a las 15:45

### Requirement: Resultado y consumo
Al terminar, el adaptador SHALL entregar `ok`, el texto final, el código de salida, la duración, las negaciones de
permisos y el consumo normalizado (`tokens_entrada`, `tokens_salida`, `tokens_cache_lectura`,
`tokens_cache_escritura`, `costo_usd`, `costo_estimado`), con `null` en lo que el agente no informa.

#### Scenario: Consumo de Claude Code
- **WHEN** el evento `result` de `cc` trae `usage` y `total_cost_usd`
- **THEN** el consumo trae esos tokens, `costo_usd` igual a `total_cost_usd` y `costo_estimado: true`

#### Scenario: Agente termina sin evento final
- **WHEN** el proceso termina con código distinto de cero y sin evento de resultado
- **THEN** el adaptador entrega `ok: false` con un error de clase `agente` y el final de la salida de error ya redactado

### Requirement: Ejecutable falso para pruebas
El repo SHALL traer un ejecutable falso (`agente_falso.py --como cc`) que, según un guion, emite el formato nativo
de Claude Code (eventos, resultado, consumo, límite de uso, error, cuelgue y proceso hijo) y deja en un archivo los
argumentos, la entrada y los nombres de las variables de entorno. Las pruebas MUST correr sin red ni agentes reales.

#### Scenario: Guion de límite de uso
- **WHEN** una prueba corre el falso con el guion `limite`
- **THEN** el falso emite la señal de límite de Claude Code y termina como lo haría el real según la documentación

#### Scenario: Sin red
- **WHEN** se corre toda la batería de pruebas con la red bloqueada salvo loopback
- **THEN** todas las pruebas pasan

### Requirement: Herramientas informadas al iniciar
Cada adaptador SHALL entregar, al traducir el aviso de inicio del agente, la lista de herramientas y la de
servidores MCP que el agente dice tener, y SHALL declarar sus herramientas propias toleradas: las que el agente
agrega aunque no se pidan y que se verificaron con el binario real. Un adaptador cuyo agente no informa sus
herramientas MUST declararlo.

#### Scenario: Inicio de cc
- **WHEN** el adaptador `cc` traduce un `system/init` con `tools` y `mcp_servers`
- **THEN** el evento `inicio` trae `herramientas` con los nombres de `tools` (hasta 40, con la cuenta de los omitidos) y `mcp` con los nombres de `mcp_servers`

#### Scenario: Lista tolerada fija
- **WHEN** se consulta la lista tolerada de `cc`
- **THEN** es una constante del código, ningún nombre empieza con `mcp__` y cada nombre trae la versión y la fecha en que se verificó

### Requirement: Uso del plan informado por el agente
El adaptador `cc` SHALL leer `utilization` y `resetsAt` de cada `rate_limit_event` y entregarlos normalizados
(fracción de 0 a 1 y hora ISO con zona) junto con la hora en que los vio. Si el agente no informa el uso, o lo
informa fuera de escala, MUST entregar `null` y nunca una estimación propia.

#### Scenario: Evento con uso
- **WHEN** el falso de `cc` emite `rate_limit_event` con `status: "allowed_warning"` y `utilization: 62`
- **THEN** el adaptador informa un uso del plan de 0,62 y la hora del aviso, sin marcar límite

#### Scenario: Uso fuera de escala
- **WHEN** el falso de `cc` emite `utilization: 250`
- **THEN** el uso del plan queda `null`

#### Scenario: Sin dato de uso
- **WHEN** una corrida de `cc` termina sin ningún `rate_limit_event`
- **THEN** el uso del plan queda `null`
