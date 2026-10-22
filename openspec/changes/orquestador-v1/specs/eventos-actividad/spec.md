# Spec Delta

## Purpose

Deja un registro append-only de lo que hace cada agente, con un formato común que no depende del agente, para
seguir las tareas en vivo y auditarlas después sin guardar datos ni secretos.

## ADDED Requirements

### Requirement: Registro JSONL append-only por proyecto
El orquestador SHALL agregar cada evento como una línea JSON en `eventos\eventos.jsonl` del proyecto, sin
modificar ni borrar líneas ya escritas (salvo la rotación). Cada línea MUST terminar en salto de línea; un
lector MUST ignorar una última línea sin salto.

#### Scenario: Evento agregado
- **WHEN** un agente informa que editó un archivo
- **THEN** `eventos.jsonl` gana exactamente una línea nueva al final y las anteriores quedan iguales

#### Scenario: Línea a medio escribir
- **WHEN** el tablero lee el archivo mientras el orquestador escribe una línea
- **THEN** el tablero ignora la línea incompleta y la lee completa en la siguiente lectura

### Requirement: Esquema normalizado de eventos
Cada evento SHALL tener `v`, `ts`, `proyecto`, `tarea`, `intento`, `agente`, `seq`, `tipo` y `datos`. `tipo`
MUST ser uno de `inicio`, `mensaje`, `herramienta`, `archivo`, `comando`, `fin`, `error` o `gate` (decisiones de
gate, spec `aprobacion-gates`), y `datos` MUST tener solo los campos definidos para ese tipo, sin importar qué
agente lo originó.

#### Scenario: Campos por tipo
- **WHEN** se normaliza un evento de cualquier agente
- **THEN** `inicio` trae `sesion`, `modelo` y `retomada`; `mensaje` trae `texto`; `herramienta` trae `nombre`, `objetivo` y `estado`; `archivo` trae `ruta` y `accion`; `comando` trae `comando`, `estado` y `codigo_salida`; `fin` trae `ok`, `duracion_s` y `consumo`; `error` trae `clase` y `mensaje`; `gate` trae `decision`, `huella`, `via` y `sesion`

#### Scenario: Evento del propio orquestador
- **WHEN** el orquestador registra un error que no viene de un agente (por ejemplo, un gate pedido por archivo)
- **THEN** el evento lleva `agente` e `intento` en `null` y el resto del esquema igual

#### Scenario: Evento desconocido del agente
- **WHEN** un agente emite un tipo de evento que el adaptador no conoce
- **THEN** no se escribe su contenido; solo se cuenta en `fin.datos.eventos_ignorados`

### Requirement: Normalización de Claude Code
El adaptador `cc` SHALL traducir su salida `stream-json` al esquema común: `system/init` a `inicio`, los bloques
de texto a `mensaje`, las herramientas de lectura y búsqueda a `herramienta`, las de edición a `archivo`, Bash a
`comando` (al iniciar y al terminar), `result` a `fin`, y los errores y el límite del plan a `error`.

#### Scenario: Corrida típica
- **WHEN** el falso de `cc` emite el guion "edita `app.py`, corre `py -3.12 -m unittest`, responde y termina con consumo"
- **THEN** la secuencia normalizada es `inicio`, `archivo`, `comando` (en_curso), `comando` (ok), `mensaje`, `fin`

#### Scenario: Negación de permiso
- **WHEN** el resultado de `cc` trae una entrada en `permission_denials`
- **THEN** queda un evento `herramienta` o `comando` con `estado: "negado"`

### Requirement: Sin contenido de archivos ni secretos
Los eventos MUST NOT guardar contenido de archivos, diffs, salidas de comandos ni resultados de herramientas.
Los textos que sí se guardan (mensajes del agente, comandos, objetivos, errores) MUST pasar por la redacción de
secretos y por el tope de largo antes de escribirse.

#### Scenario: Lectura de un archivo de datos
- **WHEN** el agente lee `datos/clientes.csv`
- **THEN** el evento `herramienta` trae solo el nombre de la herramienta y la ruta relativa, nunca el contenido leído

#### Scenario: Secreto en un comando
- **WHEN** el agente corre un comando que contiene `sk-ant-` seguido de una clave, `ghp_...`, `AKIA...`, una cabecera `Authorization:` o una llave privada PEM
- **THEN** el evento guarda el comando con esa parte reemplazada por `[REDACTADO]`

#### Scenario: Proyecto sin texto de mensajes
- **WHEN** el proyecto tiene `eventos.texto_mensajes: "nunca"`
- **THEN** los eventos `mensaje` guardan solo el largo del texto, no el texto

### Requirement: Tope por línea y por intento
Cada línea de evento SHALL medir como máximo 4 KB (los textos se truncan con la marca `…[truncado]`) y cada
intento de una tarea MUST escribir como máximo 2.000 eventos `mensaje`, `herramienta` y `comando`; pasado ese
tope solo se escriben `archivo`, `error` y `fin`, que informa cuántos se omitieron.

#### Scenario: Mensaje largo
- **WHEN** el agente emite un mensaje de 50.000 caracteres
- **THEN** la línea escrita mide 4 KB o menos y el texto termina en `…[truncado]`

#### Scenario: Agente muy conversador
- **WHEN** un intento genera 3.000 eventos de herramienta
- **THEN** se escriben 2.000 y el evento `fin` trae `eventos_omitidos: 1000`

### Requirement: Rotación por tamaño
Cuando `eventos.jsonl` supere el tope configurado (por defecto 10 MB), el orquestador SHALL rotarlo a
`eventos.1.jsonl`, corriendo los anteriores hasta `eventos.<N>.jsonl` (por defecto N = 5) y borrando el más
antiguo. La rotación MUST hacerse entre dos líneas, nunca en medio de una.

#### Scenario: Supera el tope
- **WHEN** una escritura deja `eventos.jsonl` sobre 10 MB
- **THEN** antes de la siguiente escritura el archivo pasa a ser `eventos.1.jsonl` y se abre un `eventos.jsonl` vacío

#### Scenario: Ya hay cinco rotados
- **WHEN** se rota y existe `eventos.5.jsonl`
- **THEN** `eventos.5.jsonl` se borra, los demás suben un número y no queda ningún `eventos.6.jsonl`
