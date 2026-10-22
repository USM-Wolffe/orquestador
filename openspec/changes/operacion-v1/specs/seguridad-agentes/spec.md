# Spec Delta

## ADDED Requirements

### Requirement: Conectores de claude.ai y MCP no declarados apagados
En cada corrida, el orquestador SHALL apagar los conectores de claude.ai y todo servidor MCP que la tarea no
declare, con cada medio documentado que el agente ofrezca, y ningún medio por sí solo MUST considerarse suficiente.
En esta etapa ninguna tarea puede declarar MCP, así que todos quedan apagados.

#### Scenario: Capas en el lanzamiento de cc
- **WHEN** se arma el lanzamiento de `cc` para cualquier tarea
- **THEN** el entorno trae `ENABLE_CLAUDEAI_MCP_SERVERS=false`, el perfil trae `disableClaudeAiConnectors: true` y `"mcp__*"` en `permissions.deny`, y el comando trae `--strict-mcp-config` y `--disallowedTools` con `mcp__*`

#### Scenario: Variable heredada con otro valor
- **WHEN** el orquestador corre con `ENABLE_CLAUDEAI_MCP_SERVERS=true` en su propio entorno
- **THEN** el agente recibe `ENABLE_CLAUDEAI_MCP_SERVERS=false`

#### Scenario: Lanzamiento sin una capa
- **WHEN** un adaptador de prueba devuelve un comando de `cc` sin `--strict-mcp-config`, sin el `--disallowedTools` de MCP o sin la variable en el entorno
- **THEN** el orquestador no lanza el proceso y la tarea registra un error de clase `seguridad`

#### Scenario: Adaptador que no declara las capas
- **WHEN** un adaptador de prueba llamado `cc` no declara capas propias y devuelve un comando sin `--strict-mcp-config`, o el agente no tiene capas fijadas en el núcleo
- **THEN** el orquestador no lanza el proceso y la tarea registra un error de clase `seguridad`

#### Scenario: Proyecto que abre MCP
- **WHEN** un `proyecto.json` trae en `permitir_extra` una regla que empieza con `mcp__`
- **THEN** el proyecto queda inactivo con un error que nombra la regla

### Requirement: Herramientas comprobadas al iniciar la corrida
El orquestador SHALL comparar las herramientas y los servidores MCP que el agente informa al iniciar con la lista
pedida más las herramientas propias toleradas de ese agente. Si sobra alguna herramienta, si hay algún servidor
MCP, si el aviso no trae esas listas o si no llega antes de la primera acción, MUST cortar la corrida y su árbol de
procesos antes de que siga. La tarea queda `fallida` con clase `seguridad`, sin consumir reintentos.

#### Scenario: Conectores presentes
- **WHEN** el falso de `cc` emite `system/init` con `tools` que incluye `mcp__claude_ai_Google_Drive__share_file`
- **THEN** el orquestador termina el proceso y su árbol, la tarea queda `fallida` con clase `seguridad` sin consumir reintentos, y el error nombra las herramientas que sobraban

#### Scenario: Servidor MCP todavía conectando
- **WHEN** `system/init` trae `tools` correctas pero `mcp_servers` con un servidor en estado `pending`
- **THEN** la corrida se corta igual, con clase `seguridad`

#### Scenario: Aviso sin listas
- **WHEN** `system/init` no trae `tools` o no trae `mcp_servers` como listas
- **THEN** la corrida se corta con clase `seguridad` y el motivo "el agente no informó sus herramientas"

#### Scenario: Sin aviso de inicio
- **WHEN** el agente emite un `tool_use` antes de cualquier `system/init`
- **THEN** la corrida se corta con clase `seguridad` y el motivo "el agente no informó sus herramientas"

#### Scenario: Salida que no se puede revisar
- **WHEN** después de un inicio limpio el agente emite un mensaje `assistant` cuyo `message` no tiene la forma esperada
- **THEN** la corrida se corta con clase `seguridad`, el proceso y su árbol terminan y el agente no sigue corriendo sin vigilancia

#### Scenario: Inicio limpio
- **WHEN** `system/init` trae solo herramientas pedidas o toleradas de `cc` y `mcp_servers` vacío
- **THEN** la corrida sigue y el evento `inicio` registra la lista de herramientas

#### Scenario: Herramienta pedida que falta
- **WHEN** `system/init` trae menos herramientas que las pedidas y ninguna de más
- **THEN** la corrida sigue

### Requirement: Herramientas vigiladas durante la corrida
Durante la corrida, el orquestador SHALL revisar el nombre de cada herramienta que el agente pide usar y MUST
cortar la corrida con clase `seguridad` si no está entre las comprobadas al iniciar. Esta revisión es detección: el
tablero y la matriz de garantías MUST decir que no garantiza que la llamada no haya empezado.

#### Scenario: Herramienta que aparece tarde
- **WHEN** después de un inicio limpio el falso de `cc` emite un `tool_use` con nombre `mcp__claude_ai_Gamma__generate`
- **THEN** el orquestador corta la corrida, la tarea queda `fallida` con clase `seguridad` y el evento `error` nombra la herramienta

### Requirement: Garantía declarada de los conectores
La matriz de niveles de garantía SHALL incluir el control "conectores y MCP no declarados" para cada agente, y el
evento `inicio` MUST traerlo como los demás controles.

#### Scenario: Matriz de cc
- **WHEN** arranca una tarea de `cc` en Windows nativo
- **THEN** el evento `inicio` declara `duro` para "conectores y MCP no declarados", junto a los controles que ya declaraba
