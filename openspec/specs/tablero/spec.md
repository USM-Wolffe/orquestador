# tablero Specification

## Purpose
Le muestra a Sebastian, en el navegador y en vivo, el estado de cada tarea, quién la ejecuta, qué está haciendo el
agente y cuánto consume, sin quedar expuesto fuera del PC y sin cambiar nada salvo la decisión de los gates.

## Requirements

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
Al arrancar y cada vez que Sebastian lo pide en la terminal del orquestador, el tablero SHALL generar un token de
entrada aleatorio de al menos 32 bytes y mostrar solo en la terminal el enlace
`http://127.0.0.1:<puerto>/entrar?t=<token>`. Hay un solo token vigente a la vez: uno nuevo anula al anterior.
El token vence a los 5 minutos o en su primer uso, que lo canjea por una cookie de sesión aleatoria, sin
`Max-Age` ni `Expires`. Ni el token ni la sesión MUST escribirse a disco.

#### Scenario: Sin sesión
- **WHEN** un programa del PC pide `/api/tareas` o `/api/tablero` sin cookie de sesión
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

#### Scenario: Enlace vencido
- **WHEN** se usa un enlace 5 minutos después de generado, sin haberlo canjeado
- **THEN** recibe 401 y no se crea ninguna sesión

#### Scenario: Enlace anulado por uno nuevo
- **WHEN** Sebastian pide un enlace nuevo y después se usa el anterior, que no se había canjeado
- **THEN** el anterior recibe 401 y el nuevo sigue sirviendo

#### Scenario: Aviso de sesión nueva
- **WHEN** se canjea un enlace
- **THEN** la terminal muestra una línea con la hora y el número de sesiones abiertas, sin el token ni la cookie

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
El tablero MUST NOT escribir, crear, mover ni borrar archivos, y ninguna petición HTTP al tablero MUST lanzar
procesos: abrir el navegador lo hace solo la terminal del orquestador (spec `acceso-tablero`). Acepta `GET` y
`HEAD` en todas sus rutas y `POST` solo en las dos rutas de gate de la spec `aprobacion-gates`; cualquier otro
método o ruta de escritura recibe 405.

#### Scenario: Batería de peticiones
- **WHEN** se piden todas las rutas del tablero, con y sin sesión, y además `POST`, `PUT`, `PATCH` y `DELETE` a cada ruta que no es de gate
- **THEN** el contenido y la fecha de modificación de todos los archivos de la raíz de estado y de la carpeta de Cowork quedan iguales, y no se lanza ningún proceso

#### Scenario: Método de escritura
- **WHEN** llega un `POST /api/tareas` o un `POST /api/tablero`
- **THEN** el tablero responde 405

### Requirement: Detalle de tarea en vivo
El detalle de una tarea SHALL abrirse en un panel lateral de la página principal, sin cambiar de página, con: qué
se aprueba, lo que dice la revisión, qué cambió (`diff --stat`), la bitácora del intento actual en frases y, para
una tarea en `esperando_gate`, la decisión. Los campos, el historial, el resultado, el consumo, el informe y los
niveles de garantía MUST quedar en una sección plegada de detalles técnicos. La actividad MUST llegar en no más de
3 segundos.

#### Scenario: Actividad en vivo
- **WHEN** el agente de la tarea abierta edita un archivo
- **THEN** la bitácora del panel muestra "Editó <archivo>" en no más de 3 segundos, sin recargar la página

#### Scenario: Tarea esperando gate
- **WHEN** Sebastian abre una tarea en `esperando_gate`
- **THEN** ve qué se aprueba, la revisión, el `diff --stat`, la huella corta y los botones Aprobar y Rechazar con un comentario, y al pulsar Aprobar aparece el campo del código de la terminal

#### Scenario: Detalles técnicos
- **WHEN** Sebastian despliega "Detalles técnicos" en el panel
- **THEN** ve el id, el agente, los intentos, el historial, los niveles de garantía, el consumo y el informe completo

#### Scenario: Cerrar el panel
- **WHEN** el panel está abierto y Sebastian pulsa Escape, la × o fuera del panel
- **THEN** el panel se cierra y la página principal sigue actualizándose

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

### Requirement: Te toca decidir
La página principal SHALL empezar con la sección "Te toca decidir", con una entrada por cada tarea en
`esperando_gate` del proyecto elegido: título, explicación de lo que se aprueba, evidencia y un botón "Revisar y
decidir" que abre el panel. Si no hay ninguna, MUST mostrar una sola línea "Nada que decidir ahora" y ningún otro
contenido en esa sección.

#### Scenario: Un gate pendiente
- **WHEN** hay una tarea en `esperando_gate` con explicación y `diff --stat`
- **THEN** la sección muestra su título, la explicación, "N archivos cambiados", el resultado de la última corrida de pruebas si la hubo y el veredicto de la revisión si existe

#### Scenario: Sin gates
- **WHEN** ninguna tarea del proyecto espera gate
- **THEN** la sección muestra solo "Nada que decidir ahora"

### Requirement: Ahora mismo
La página principal SHALL tener la sección "Ahora mismo", con una fila por agente configurado: nombre y color,
qué hace en palabras simples (tarea y frase de su última acción con su antigüedad) y su consumo del día. Un agente
apagado, no disponible o con el plan agotado MUST decirlo con el motivo y, si se sabe, la hora de reinicio.

#### Scenario: Agente trabajando
- **WHEN** `cc` corre la tarea "Adaptador de Codex" y su último evento es la edición de `adaptadores/codex.py` hace 40 s
- **THEN** su fila dice "Adaptador de Codex" y "Editó adaptadores/codex.py · hace 40 s"

#### Scenario: Plan agotado
- **WHEN** `cc` llegó al límite del plan con reinicio a las 15:45
- **THEN** su fila dice "Plan agotado · sigue a las 15:45"

#### Scenario: Consumo sin porcentaje conocido
- **WHEN** el agente no informó su uso del plan
- **THEN** la fila muestra los minutos de trabajo y las tareas del día, sin barra ni porcentaje

#### Scenario: Consumo con porcentaje informado
- **WHEN** el último `rate_limit_event` de `cc` informó un uso de 0,62 hace 5 minutos
- **THEN** la fila muestra "Plan: 62 % usado" con una barra y la nota "según Claude Code, hace 5 min"

### Requirement: El plan
La página principal SHALL tener la sección "El plan", con una línea por cambio que tenga tareas no terminadas o
que haya terminado en las últimas 24 horas. Cada línea muestra sus tareas como estaciones, ordenadas por
dependencias y luego por fecha de creación. El color del punto dice el agente y su forma, el estado, y cada
estación MUST tener además el estado en texto.

#### Scenario: Línea de un cambio
- **WHEN** un cambio tiene 6 tareas: 3 hechas, 1 en `esperando_gate` y 2 bloqueadas
- **THEN** su línea dice "3 de 6 listas", las estaciones van en orden y la cuarta dice "Te espera"

#### Scenario: Leyenda
- **WHEN** se muestra la sección
- **THEN** hay una leyenda con la forma de cada estado: hecha, trabajando, te espera, bloqueada y falló

#### Scenario: Estación abre el panel
- **WHEN** Sebastian pulsa una estación
- **THEN** se abre el panel de detalle de esa tarea

### Requirement: Lenguaje simple
Los textos del tablero SHALL estar en lenguaje simple en español de Chile y MUST NOT mostrar nombres internos de
estados, clases de error ni tipos de evento fuera de los detalles técnicos.

#### Scenario: Estados en palabras
- **WHEN** se muestran tareas en `esperando_gate`, `bloqueada` por T-2, `en_curso` hace 12 min, `pendiente`, `fallida` por `timeout` y `cancelada`
- **THEN** se leen "Te espera", "Espera a T-2" (o "Espera a la anterior" si T-2 es la estación previa), "Trabajando, 12 min", "En cola", "Falló: se le acabó el tiempo" y "Cancelada"

#### Scenario: Falla de seguridad
- **WHEN** una tarea quedó `fallida` con clase `seguridad` por herramientas no pedidas
- **THEN** la estación dice "Se detuvo por seguridad" y el panel explica qué herramientas aparecieron

### Requirement: Bitácora en frases
El panel SHALL traducir los eventos del intento actual a frases cortas con su hora, en orden, juntando las
repeticiones seguidas de la misma frase. Los mensajes del agente MUST NOT aparecer como frases y las negaciones
MUST aparecer siempre.

#### Scenario: Frases de eventos comunes
- **WHEN** el intento tiene `inicio`, `herramienta` leer `docs/diseno.md`, `archivo` editar `orquestador/tablero.py` dos veces, `comando` `py -3.12 -m unittest` con estado `ok` y `fin` con `ok: true`
- **THEN** la bitácora dice "Empezó", "Leyó docs/diseno.md", "Editó orquestador/tablero.py (2 veces)", "Corrió las pruebas" y "Terminó y entregó su informe"

#### Scenario: Comando negado
- **WHEN** el intento tiene un `comando` `git push origin main` con estado `negado`
- **THEN** la bitácora dice "Intentó git push y se le negó"

### Requirement: API de la vista principal
El tablero SHALL ofrecer `GET /api/tablero?proyecto=<p>` con todo lo que la página principal necesita en una sola
respuesta: gates pendientes, filas de agentes, líneas del plan y la hora del último ciclo del orquestador. La
respuesta MUST pasar por la misma redacción que el detalle y no traer prompts.

#### Scenario: Datos que faltaban
- **WHEN** se pide `/api/tablero` con un gate pendiente revisado y un agente trabajando
- **THEN** la respuesta trae la explicación de lo que se aprueba, el veredicto y el resumen de la revisión, la frase de la última acción con su hora y el consumo del día de cada agente

#### Scenario: Sin prompt
- **WHEN** una tarea tiene un prompt con texto libre
- **THEN** ninguna parte de la respuesta de `/api/tablero` lo contiene

### Requirement: Estáticos sin código en línea
La página principal SHALL servirse como HTML, CSS y JS propios en archivos aparte, sin `<script>` ni `<style>` en
línea, sin atributos `style`, `on*` ni `javascript:` en el HTML, y solo con fuentes del sistema (Bahnschrift y
Segoe UI). La CSP MUST seguir siendo `default-src 'none'` con solo recursos propios.

#### Scenario: Revisión de los estáticos
- **WHEN** las pruebas leen los HTML servidos por el tablero
- **THEN** no encuentran `<script>` sin `src`, `<style>`, atributos `style` ni `on*`, ni `@font-face` o `url(` hacia fuera en el CSS

#### Scenario: Textos de las tareas
- **WHEN** el título de una tarea trae `<img src=x onerror=alert(1)>`
- **THEN** el tablero lo muestra como texto y no crea ningún elemento

### Requirement: Página sin sesión
Una petición a `/` sin sesión válida SHALL recibir 401 con una página fija que explica cómo entrar (pulsar Enter
en la ventana del orquestador) y MUST NOT traer datos del estado.

#### Scenario: Abrir sin sesión
- **WHEN** el navegador pide `/` sin cookie de sesión
- **THEN** recibe 401 y una página que dice "Pulsa Enter en la ventana del orquestador para entrar", sin proyectos, tareas ni agentes
