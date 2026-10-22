# Spec Delta

## MODIFIED Requirements

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

## ADDED Requirements

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
