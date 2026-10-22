# Spec Delta

## Purpose

Permite que Sebastian apruebe o rechace los gates con un botón del tablero, con defensas para que un agente u otro
programa del PC no pueda decidir en su nombre, y declara con honestidad lo que esas defensas no cubren.

## ADDED Requirements

### Requirement: Única acción de escritura del tablero
La decisión de un gate (aprobar, o rechazar con nota) SHALL ser la única acción del tablero que cambia el estado, y
solo para tareas en `esperando_gate`. El tablero MUST entregarla en memoria al bucle de `orq correr`, que la
valida y la aplica; el tablero MUST NOT escribir archivos para hacerlo.

#### Scenario: Aprobación aplicada por el bucle
- **WHEN** el flujo de aprobación de T-7 termina bien
- **THEN** la decisión llega al bucle por la cola en memoria, el bucle cambia `tareas.json` y ningún archivo nuevo aparece en `decisiones\`

#### Scenario: Gate de una tarea que no espera gate
- **WHEN** llega una decisión de gate para una tarea en `en_curso`
- **THEN** el tablero responde 409 y la tarea no cambia

### Requirement: Confirmación en dos pasos con código en la terminal
El primer paso (`preparar`) SHALL hacer que el orquestador imprima en su terminal un código de 6 dígitos, de un
solo uso y válido por 120 segundos, ligado a la tarea, la decisión y la huella. El segundo paso (`confirmar`) MUST
traer ese código. El código MUST NOT aparecer en respuestas HTTP, registros, eventos ni archivos.

#### Scenario: Código correcto
- **WHEN** Sebastian pulsa Aprobar, lee el código en la terminal y lo escribe en el tablero antes de 120 s
- **THEN** la aprobación se aplica y el código deja de servir

#### Scenario: Código vencido o usado
- **WHEN** se confirma con un código vencido o que ya se usó
- **THEN** el tablero responde 403 y la tarea sigue en `esperando_gate`

#### Scenario: El código no sale de la terminal
- **WHEN** termina un flujo completo de aprobación en una prueba
- **THEN** el código no aparece en ninguna respuesta HTTP ni en ningún archivo de la raíz de estado, la carpeta de Cowork o el directorio temporal

### Requirement: Aprobación atada a la huella del estado
El orquestador SHALL calcular la huella de una tarea en `esperando_gate` como SHA-256 del id, el intento, el HEAD del
worktree, `git diff --binary HEAD`, los archivos sin seguimiento con su SHA-256 y el SHA-256 del informe. El
tablero MUST mostrarla, y ambos pasos MUST enviarla; si no coincide con la recalculada, la decisión se rechaza.

#### Scenario: El worktree cambió después de revisar
- **WHEN** Sebastian abrió T-7 con la huella H1 y antes de confirmar un archivo del worktree cambió
- **THEN** el tablero responde 409 "el estado cambió, vuelve a revisar" y la tarea sigue en `esperando_gate`

#### Scenario: Archivo nuevo sin seguimiento
- **WHEN** después de mostrar la huella aparece un archivo nuevo sin seguimiento en el worktree
- **THEN** la huella recalculada es distinta y la decisión se rechaza

### Requirement: Protección de origen y CSRF en el gate
Las dos rutas del gate SHALL aceptar solo `POST` con la cookie de sesión vigente, la cabecera con el token CSRF de
esa sesión, `Origin` y `Host` iguales a los del propio tablero y `Content-Type: application/json`. Cualquier
falta MUST responder 401 o 403 sin cambiar nada.

#### Scenario: Sin token CSRF
- **WHEN** llega un `POST` de gate con cookie válida pero sin la cabecera CSRF
- **THEN** el tablero responde 403

#### Scenario: Origen ajeno
- **WHEN** llega un `POST` de gate con `Origin: http://otro.example`
- **THEN** el tablero responde 403

#### Scenario: Sin sesión
- **WHEN** llega un `POST` de gate sin cookie de sesión
- **THEN** el tablero responde 401

### Requirement: Bloqueo por códigos erróneos
Después de 3 confirmaciones con código erróneo en la misma ejecución, el orquestador SHALL deshabilitar todas las
decisiones de gate hasta reiniciarse, imprimirlo en la terminal y registrar un evento `error` de clase
`seguridad`.

#### Scenario: Tres códigos malos
- **WHEN** llegan tres confirmaciones con código erróneo
- **THEN** la cuarta, aunque traiga el código correcto, recibe 423 y el tablero muestra "gates bloqueados hasta reiniciar"

### Requirement: Registro de cada decisión
Cada decisión aplicada SHALL quedar en el historial de la tarea con `por: sebastian`, `via: tablero`, la huella,
un identificador corto de la sesión del tablero y la hora; MUST emitir un evento `gate` y una línea en la
terminal del orquestador.

#### Scenario: Rastro de una aprobación
- **WHEN** Sebastian aprueba T-7
- **THEN** el historial, `eventos.jsonl`, la salida de Cowork y la terminal muestran la aprobación con su huella y su hora

### Requirement: Aviso de integridad del código del orquestador
Al iniciar, el orquestador SHALL revisar si el árbol de su instalación tiene cambios sin commit. Si los tiene,
MUST mostrarlo en la terminal y en el tablero y deshabilitar las decisiones de gate, salvo que se haya iniciado con
`--permitir-codigo-modificado`.

#### Scenario: Código modificado
- **WHEN** `orq correr` arranca con un archivo de `orquestador/` modificado y sin commit
- **THEN** el tablero muestra el aviso y los botones de gate quedan deshabilitados

#### Scenario: Modo desarrollo explícito
- **WHEN** arranca con `--permitir-codigo-modificado`
- **THEN** los gates funcionan, el aviso se mantiene visible y la decisión queda marcada en el historial
