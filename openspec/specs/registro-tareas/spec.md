# registro-tareas Specification

## Purpose
Define el registro de tareas de cada proyecto como fuente de verdad: qué campos tiene una tarea, por qué estados
pasa, quién puede mover cada transición y cómo Cowork y Sebastian piden cambios sin pisarse.

## Requirements

### Requirement: Registro JSON por proyecto con un solo escritor
Cada proyecto SHALL tener `tareas.json` como fuente de verdad de sus tareas. Solo el proceso `orq correr` MUST
escribirlo, siempre con escritura atómica (archivo temporal y reemplazo) y dejando la versión anterior en
`tareas.json.bak`. Cowork, Sebastian y el tablero no lo escriben.

#### Scenario: Escritura atómica
- **WHEN** el orquestador cambia el estado de una tarea
- **THEN** escribe `tareas.json.tmp`, guarda la versión previa como `tareas.json.bak` y reemplaza `tareas.json`

#### Scenario: Registro corrupto al iniciar
- **WHEN** `tareas.json` no se puede leer como JSON y `tareas.json.bak` sí
- **THEN** el orquestador usa la copia, deja el archivo dañado como `tareas.json.danado-<marca>` y lo registra como error

#### Scenario: Reemplazo con el archivo abierto por un lector
- **WHEN** otro proceso tiene `tareas.json` abierto en el momento del reemplazo y Windows lo impide
- **THEN** el orquestador reintenta el reemplazo durante al menos 2 segundos antes de dar error, sin perder el cambio

#### Scenario: Escritura externa detectada
- **WHEN** alguien modifica `tareas.json` por fuera mientras el orquestador corre
- **THEN** el orquestador conserva su versión, guarda la ajena como `tareas.json.externo-<marca>` y registra el error

### Requirement: Campos mínimos de una tarea
Cada tarea SHALL tener: `id`, `titulo`, `prompt`, `agente`, `agentes_permitidos`, `estado`, `dependencias`,
`cambio`, `rama`, `gate`, `intentos`, `max_intentos`, `resultado`, `consumo`, `creada`, `actualizada`,
`iniciada`, `terminada` e `historial`. Puede tener además `base`, `red`, `prioridad`, `nueva_sesion`,
`timeout_min`, `no_antes_de`, `explicacion` y `revisa`.

#### Scenario: Tarea creada con lo mínimo
- **WHEN** Cowork crea una tarea con `id`, `titulo`, `prompt`, `agente` y `cambio`
- **THEN** el orquestador completa `agentes_permitidos` con `[agente]`, `dependencias` con `[]`, `rama` con el nombre del cambio, `gate` según `gate_por_defecto` del proyecto, `intentos` en 0, `max_intentos` en 3 y las marcas de tiempo

#### Scenario: Agente no permitido
- **WHEN** una tarea pide un agente que no está configurado, que no está habilitado o que el proyecto no permite
- **THEN** la solicitud se rechaza con un error de validación

#### Scenario: Explicación de la tarea
- **WHEN** Cowork crea una tarea con `explicacion` de hasta 300 caracteres sin saltos de línea
- **THEN** la tarea la guarda y el tablero la muestra como "Qué se aprueba"

#### Scenario: Explicación inválida
- **WHEN** `explicacion` pasa de 300 caracteres o trae caracteres de control
- **THEN** la solicitud se rechaza con un error de validación

### Requirement: Estados de una tarea
El estado de una tarea SHALL ser uno de: `pendiente`, `bloqueada`, `en_curso`, `esperando_gate`, `hecha`,
`fallida` o `cancelada`. `hecha` y `cancelada` MUST ser terminales. Cada transición MUST quedar en `historial`
con el estado de origen, el de destino, quién la movió (`orquestador`, `cowork` o `sebastian`), la marca de
tiempo y el motivo.

#### Scenario: Historial de una transición
- **WHEN** una tarea pasa de `pendiente` a `en_curso`
- **THEN** `historial` gana una entrada con `de: pendiente`, `a: en_curso`, `por: orquestador`, la hora y el motivo

#### Scenario: Tarea terminal
- **WHEN** llega una solicitud de editar o reintentar una tarea `hecha` o `cancelada`
- **THEN** la solicitud se rechaza y la tarea no cambia

### Requirement: Transiciones que mueve el orquestador
Solo el orquestador SHALL mover: creación a `pendiente` o `bloqueada`; `bloqueada`→`pendiente` y
`pendiente`→`bloqueada` según dependencias; `pendiente`→`en_curso`; `en_curso`→`esperando_gate`, `hecha`,
`pendiente` (límite de plan, interrupción o reintento) o `fallida`; y ejecutar las cancelaciones y las
decisiones de gate pedidas.

#### Scenario: Termina bien sin gate
- **WHEN** el agente de una tarea sin gate termina sin error
- **THEN** el orquestador la pasa a `hecha`

#### Scenario: Termina bien con gate
- **WHEN** el agente de una tarea con gate termina sin error
- **THEN** el orquestador la pasa a `esperando_gate` y calcula la huella del estado que se mostrará para aprobar

#### Scenario: Error con intentos disponibles
- **WHEN** el agente termina con error, no es límite de plan y `intentos` es menor que `max_intentos`
- **THEN** la tarea vuelve a `pendiente` y `intentos` sube en uno

#### Scenario: Error sin intentos disponibles
- **WHEN** el agente termina con error y `intentos` llegó a `max_intentos`
- **THEN** la tarea pasa a `fallida` con el error en `resultado`

### Requirement: Gates que decide Sebastian en el tablero
Solo Sebastian SHALL decidir los gates, desde el botón del tablero, con el flujo de la spec `aprobacion-gates`:
`esperando_gate`→`hecha` (aprobar) o `esperando_gate`→`pendiente` (rechazar con nota, que se agrega al prompt del
siguiente intento en la misma sesión). Una decisión de gate que no llega por ese flujo MUST rechazarse.

#### Scenario: Aprobar un gate
- **WHEN** Sebastian aprueba T-7 en el tablero con la huella vigente y el código correcto
- **THEN** T-7 pasa a `hecha` con `por: sebastian` y `via: tablero` en el historial

#### Scenario: Rechazar con nota
- **WHEN** Sebastian rechaza T-7 con la nota "falta la prueba del caso vacío"
- **THEN** T-7 vuelve a `pendiente` y el siguiente intento recibe la nota junto al prompt, en la misma sesión del cambio

#### Scenario: Decisión de gate por archivo
- **WHEN** aparece en `decisiones\` o en la entrada de Cowork un archivo que pide aprobar o rechazar un gate
- **THEN** el orquestador lo rechaza, no cambia la tarea y registra un evento `error` de clase `seguridad`

### Requirement: Reintento y cancelación por Sebastian
Sebastian SHALL poder pedir, con `orq tarea <proyecto> <id> reintentar|cancelar`, el reintento de una tarea
`fallida` y la cancelación de una tarea no terminal (incluida una en `esperando_gate`). La solicitud va a
`decisiones\` y el orquestador la aplica con `por: sebastian`.

#### Scenario: Reintento de una tarea fallida
- **WHEN** Sebastian pide reintentar T-9, que está `fallida` con `intentos: 3` y `max_intentos: 3`
- **THEN** T-9 pasa a `pendiente` con `max_intentos: 4` y `por: sebastian`

#### Scenario: Cancelar una tarea que espera gate
- **WHEN** Sebastian cancela T-7, que está en `esperando_gate`
- **THEN** T-7 pasa a `cancelada` y su cambio queda libre para otras tareas

### Requirement: Transiciones que pide Cowork
Cowork SHALL poder crear tareas, editar las que están en `pendiente`, `bloqueada` o `fallida`, pedir
`fallida`→`pendiente` (reintento) y pedir la cancelación de tareas que no están en un estado terminal. Cowork
MUST NOT poder aprobar ni rechazar gates ni fijar `estado`, `intentos`, `resultado`, `consumo` ni `historial`.

#### Scenario: Cowork intenta aprobar un gate
- **WHEN** una solicitud en la entrada de Cowork trae `op: "aprobar"` o un campo `estado`
- **THEN** la solicitud se rechaza y ninguna tarea cambia

#### Scenario: Cowork edita una tarea en curso
- **WHEN** Cowork pide editar el prompt de una tarea `en_curso`
- **THEN** la solicitud se rechaza con el motivo "la tarea está en curso"

#### Scenario: Cowork cancela una tarea en curso
- **WHEN** Cowork pide cancelar una tarea `en_curso`
- **THEN** el orquestador detiene el proceso del agente y la tarea pasa a `cancelada` con `por: cowork`

### Requirement: Entrada de solicitudes de Cowork
Cowork SHALL pedir cambios dejando archivos `*.json` en `entrada\` de la carpeta de Cowork del proyecto, con
`op` = `crear`, `editar`, `cancelar` o `reintentar`. El orquestador MUST procesarlos en orden de nombre, validar
cada uno, aplicarlo entero o no aplicarlo, moverlo a `entrada\procesadas\` y dejar el acuse en
`respuestas\<mismo nombre>`.

#### Scenario: Lote de tareas con dependencias
- **WHEN** una solicitud `crear` trae tres tareas donde la tercera depende de las dos primeras
- **THEN** las tres quedan en el registro y la tercera queda `bloqueada`

#### Scenario: Solicitud inválida
- **WHEN** una solicitud trae una dependencia a una tarea que no existe o forma un ciclo
- **THEN** no se aplica ninguna parte de la solicitud y el acuse dice `ok: false` con el error

#### Scenario: Id repetido
- **WHEN** una solicitud `crear` usa un `id` que ya existe en el proyecto
- **THEN** la solicitud se rechaza

### Requirement: Sin escrituras a medias en la entrada
El orquestador SHALL ignorar los archivos de la entrada que no terminan en `.json` (Cowork escribe primero
`*.tmp` y luego renombra). Un `.json` que no se puede leer MUST reintentarse en los ciclos siguientes y, si sigue
ilegible después de 60 segundos, moverse a `entrada\rechazadas\` con su acuse de error.

#### Scenario: Archivo temporal
- **WHEN** en la entrada hay `0007-lote.json.tmp`
- **THEN** el orquestador no lo procesa

#### Scenario: JSON incompleto que se completa
- **WHEN** un `.json` no se puede leer en un ciclo y en el siguiente ya está completo
- **THEN** el orquestador lo procesa normalmente

### Requirement: Tarea de revisión
Una tarea con `revisa: <id>` SHALL ser la revisión de otra tarea del mismo cambio. El orquestador MUST rechazar
la solicitud si `<id>` no existe en el proyecto, es de otro cambio o es la misma tarea, y MUST agregar `<id>` a sus
dependencias. El veredicto se lee solo de la primera línea del informe de la revisión.

#### Scenario: Revisión válida
- **WHEN** Cowork crea T-4r con `revisa: "T-4"`, en el mismo cambio que T-4
- **THEN** T-4r queda con T-4 entre sus dependencias y el tablero muestra su veredicto en el gate correspondiente

#### Scenario: Revisión de otro cambio
- **WHEN** `revisa` apunta a una tarea de otro cambio
- **THEN** la solicitud se rechaza con un error de validación

#### Scenario: Veredicto
- **WHEN** el informe de T-4r empieza con `Veredicto: con reparos`
- **THEN** el veredicto es `con_reparos` y el resumen son los primeros 500 caracteres que siguen, redactados

#### Scenario: Informe sin veredicto
- **WHEN** la primera línea del informe no calza con `Veredicto: sin reparos|con reparos|no concluyente`
- **THEN** el veredicto es `no_concluyente`
