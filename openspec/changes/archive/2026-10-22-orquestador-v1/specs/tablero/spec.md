# Spec Delta

## Purpose

Le muestra a Sebastian, en el navegador y en vivo, el estado de cada tarea, quién la ejecuta, qué está haciendo el
agente y cuánto consume, sin quedar expuesto fuera del PC y sin cambiar nada salvo la decisión de los gates.

## ADDED Requirements

### Requirement: Tablero dentro del orquestador
El tablero SHALL correr como un hilo del proceso `orq correr`, que lo levanta por defecto y lo omite con
`--sin-tablero`. El tablero MUST NOT existir como proceso aparte con acceso al estado.

#### Scenario: Arranque con tablero
- **WHEN** Sebastian corre `orq correr`
- **THEN** el mismo proceso atiende el bucle y el tablero, y la terminal muestra el enlace de entrada

#### Scenario: Sin tablero
- **WHEN** Sebastian corre `orq correr --sin-tablero`
- **THEN** no se abre ningún puerto

### Requirement: Solo en 127.0.0.1
El tablero SHALL escuchar únicamente en `127.0.0.1`. La dirección MUST estar fija en el código y no ser
configurable; el puerto sí es configurable (por defecto 8765) y, si está ocupado, `orq correr` MUST terminar con
un error en vez de buscar otro.

#### Scenario: Dirección de escucha
- **WHEN** el tablero arranca
- **THEN** el socket queda en `127.0.0.1:<puerto>` y no en `0.0.0.0` ni en otra interfaz

#### Scenario: Conexión desde otra interfaz
- **WHEN** se intenta conectar al puerto del tablero usando una IP del PC que no es `127.0.0.1`
- **THEN** la conexión es rechazada

### Requirement: Acceso con enlace de un solo uso y sesión en memoria
Al arrancar, el tablero SHALL generar un token de entrada aleatorio de al menos 32 bytes y mostrar solo en la
terminal el enlace `http://127.0.0.1:<puerto>/entrar?t=<token>`. El primer uso lo canjea por una cookie de sesión
aleatoria, y el token deja de servir. Ni el token ni la sesión MUST escribirse a disco.

#### Scenario: Sin sesión
- **WHEN** un programa del PC pide `/api/tareas` sin cookie de sesión
- **THEN** recibe 401 y ningún dato del estado

#### Scenario: Canje del enlace
- **WHEN** el navegador abre el enlace con el token vigente
- **THEN** recibe una cookie `HttpOnly` y `SameSite=Strict` y se le redirige a `/`, y un segundo uso del mismo enlace recibe 401

#### Scenario: Nada en disco
- **WHEN** el tablero lleva un rato corriendo con una sesión abierta
- **THEN** ningún archivo de la raíz de estado, de la carpeta de Cowork ni del directorio temporal contiene el token ni la sesión

#### Scenario: Reinicio
- **WHEN** `orq correr` se reinicia y alguien usa la cookie o el enlace anteriores
- **THEN** recibe 401

### Requirement: Defensas del navegador
El tablero SHALL rechazar con 403 las peticiones cuyo `Host` no sea `127.0.0.1:<puerto>` ni `localhost:<puerto>`,
y las que traigan un `Origin` distinto del propio. Las respuestas MUST incluir `Content-Security-Policy` que solo
permita recursos propios, `X-Frame-Options: DENY` y ninguna cabecera CORS.

#### Scenario: Rebinding de DNS
- **WHEN** llega una petición con sesión válida pero con `Host: ataque.example:8765`
- **THEN** el tablero responde 403

#### Scenario: Petición desde otra página
- **WHEN** llega una petición con `Origin: http://otro.example`
- **THEN** el tablero responde 403

### Requirement: Solo lectura salvo el gate
El tablero MUST NOT escribir, crear, mover ni borrar archivos y MUST NOT lanzar procesos. Acepta `GET` y `HEAD`
en todas sus rutas y `POST` solo en las dos rutas de gate de la spec `aprobacion-gates`; cualquier otro método o
ruta de escritura recibe 405.

#### Scenario: Batería de peticiones
- **WHEN** se piden todas las rutas del tablero, con y sin sesión, y además `POST`, `PUT`, `PATCH` y `DELETE` a cada ruta que no es de gate
- **THEN** el contenido y la fecha de modificación de todos los archivos de la raíz de estado y de la carpeta de Cowork quedan iguales

#### Scenario: Método de escritura
- **WHEN** llega un `POST /api/tareas`
- **THEN** el tablero responde 405

### Requirement: Kanban por estado
La página principal SHALL mostrar una columna por estado de tarea con una tarjeta por tarea, cada una con id,
título, proyecto, cambio, agente asignado, intentos y tiempo en el estado actual, y MUST permitir filtrar por
proyecto y por agente.

#### Scenario: Filtro por proyecto
- **WHEN** Sebastian elige el filtro del proyecto `demo`
- **THEN** solo se ven las tarjetas de `demo`, en sus columnas

#### Scenario: Agente agotado
- **WHEN** una tarea espera porque su agente llegó al límite del plan
- **THEN** su tarjeta muestra el agente, "plan agotado" y la hora de reinicio

### Requirement: Detalle de tarea en vivo
El detalle de una tarea SHALL mostrar sus campos, su historial, la actividad del intento actual (eventos
normalizados) actualizada en vivo, el resultado, el consumo, el `diff --stat` y los niveles de garantía, y para
una tarea en `esperando_gate` la huella y los botones de gate. La actividad MUST llegar en no más de 3 segundos.

#### Scenario: Actividad en vivo
- **WHEN** el agente de la tarea abierta edita un archivo
- **THEN** el detalle muestra el evento `archivo` con la ruta en no más de 3 segundos, sin recargar la página

#### Scenario: Tarea esperando gate
- **WHEN** Sebastian abre una tarea en `esperando_gate`
- **THEN** ve el `diff --stat`, el informe, la huella corta y los botones Aprobar y Rechazar con nota

### Requirement: Diff stat calculado por el orquestador
El tablero MUST NOT correr git. El orquestador SHALL calcular el `diff --stat` del worktree contra la rama base,
incluidos los archivos nuevos sin seguimiento, al terminar cada intento y, mientras la tarea está en curso, como
máximo cada 10 segundos tras un evento `archivo`, sin tomar candados del repo, en `diffstat\<id>.json`.

#### Scenario: Diff durante la ejecución
- **WHEN** el agente edita archivos durante un intento
- **THEN** `diffstat\<id>.json` se actualiza en no más de 10 segundos y el tablero lo muestra

#### Scenario: Archivo nuevo
- **WHEN** el agente crea `src/nuevo.py`, que git todavía no sigue
- **THEN** el diff stat lo muestra como archivo nuevo con sus líneas

#### Scenario: Sin diff calculado
- **WHEN** la tarea nunca corrió o el worktree ya no existe
- **THEN** el detalle muestra "diff no disponible" y el resto de la información

### Requirement: Vista de consumo por agente
El tablero SHALL tener una vista que, por agente y con filtro por proyecto y rango de fechas, muestre tareas
corridas, intentos, tiempo de ejecución, tokens de entrada, salida y caché, costo informado cuando el agente lo
entrega, veces que llegó al límite del plan y la hora del próximo reinicio conocido.

#### Scenario: Costo estimado
- **WHEN** `cc` informa `total_cost_usd` con una suscripción
- **THEN** la vista lo muestra marcado como estimado

#### Scenario: Dato que el agente no informa
- **WHEN** una corrida no trae costo
- **THEN** la vista muestra "sin costo informado" en vez de cero
