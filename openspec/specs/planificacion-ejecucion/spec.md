# planificacion-ejecucion Specification

## Purpose
Decide qué tareas corren, cuándo y dónde: paralelismo con límites, dependencias, un worktree por cambio, manejo
del límite de uso del plan y recuperación cuando el orquestador se reinicia.

## Requirements

### Requirement: Límite global y por agente
El orquestador SHALL correr a la vez como máximo `limites.global` tareas en total y `limites.por_agente[<agente>]`
tareas por agente, sumando todos los proyectos. Una tarea `pendiente` que no cabe MUST esperar sin cambiar de
estado.

#### Scenario: Límite por agente
- **WHEN** `por_agente.cc` es 1, hay una tarea de `cc` en curso y otra `pendiente` para `cc` en otro cambio
- **THEN** la segunda no arranca hasta que la primera termina, aunque haya cupo global

#### Scenario: Límite global
- **WHEN** `global` es 1, `por_agente.cc` es 2 y hay dos tareas `pendiente` de cambios distintos
- **THEN** solo una corre a la vez

#### Scenario: Cupo libre
- **WHEN** hay cupo global y por agente, y la tarea cumple las demás condiciones
- **THEN** la tarea arranca en el ciclo siguiente

### Requirement: Dependencias abiertas bloquean
Una tarea con alguna dependencia que no está `hecha` SHALL quedar `bloqueada` y MUST NOT arrancar. Cuando todas
sus dependencias quedan `hecha`, el orquestador la pasa a `pendiente`. Si una dependencia queda `fallida` o
`cancelada`, la tarea sigue `bloqueada` con ese motivo hasta que Cowork la edite o la cancele.

#### Scenario: Dependencia pendiente
- **WHEN** T-2 depende de T-1 y T-1 está `en_curso`
- **THEN** T-2 está `bloqueada` y su proceso no se lanza

#### Scenario: Dependencia esperando gate
- **WHEN** T-1 está en `esperando_gate`
- **THEN** T-2 sigue `bloqueada`

#### Scenario: Dependencias cumplidas
- **WHEN** T-1 pasa a `hecha` y era la única dependencia abierta de T-2
- **THEN** T-2 pasa a `pendiente` con `por: orquestador`

#### Scenario: Dependencia fallida
- **WHEN** T-1 pasa a `fallida`
- **THEN** T-2 sigue `bloqueada` con el motivo "dependencia T-1 fallida"

### Requirement: Un cambio a la vez, incluso esperando gate
Una tarea MUST NOT arrancar si otra tarea del mismo proyecto y del mismo `cambio` está `en_curso` o en
`esperando_gate`, aunque haya cupo, para que el worktree que Sebastian revisa no cambie antes de su decisión.

#### Scenario: Mismo cambio en curso
- **WHEN** T-1 (cambio `login`) está en curso y T-3 (cambio `login`) está `pendiente`
- **THEN** T-3 no arranca hasta que T-1 deja `en_curso`

#### Scenario: Mismo cambio esperando gate
- **WHEN** T-1 (cambio `login`) está en `esperando_gate` y T-3 (cambio `login`) está `pendiente`
- **THEN** T-3 no arranca hasta que Sebastian decide el gate de T-1 o la cancela

#### Scenario: Cambios distintos en el mismo repo
- **WHEN** T-1 (cambio `login`) y T-4 (cambio `reportes`) están `pendiente` con cupo
- **THEN** ambas pueden correr a la vez, cada una en su worktree

### Requirement: Un worktree por cambio
Cada tarea SHALL correr en el worktree de su cambio, `<carpeta_worktrees>\wt-<cambio>` (por defecto la carpeta
padre del repo), creándolo desde la rama base si no existe y reutilizándolo si existe. La creación MUST
serializarse por repo, usar el `git` de la configuración y nunca borrar worktrees ni ramas.

#### Scenario: Worktree nuevo
- **WHEN** arranca la primera tarea del cambio `login` y no existe `wt-login`
- **THEN** el orquestador crea el worktree con la rama `login` desde la base del proyecto

#### Scenario: Dos cambios nuevos a la vez
- **WHEN** dos tareas de cambios nuevos del mismo repo arrancan en el mismo ciclo
- **THEN** los dos `git worktree add` corren uno después del otro y ambos worktrees quedan creados

### Requirement: Sesión por cambio y agente
El orquestador SHALL guardar el id de sesión por `(proyecto, cambio, agente)` apenas se conoce, y retomarlo en la
siguiente tarea de ese cambio con ese agente, salvo que la tarea pida `nueva_sesion`.

#### Scenario: Retoma la sesión
- **WHEN** T-1 de `cc` en el cambio `login` terminó con la sesión S y arranca T-2 de `cc` en `login`
- **THEN** el comando de T-2 retoma la sesión S

#### Scenario: Sesión nueva pedida
- **WHEN** T-2 trae `nueva_sesion: true`
- **THEN** el comando abre una sesión nueva y la guarda en lugar de S

### Requirement: Límite de uso del plan
Cuando el adaptador detecta el límite de uso del plan, el orquestador SHALL devolver la tarea a `pendiente` sin
sumar intentos, fijar `no_antes_de` con la hora de reinicio informada (o 30 minutos si no la hay) y marcar al
agente como agotado hasta esa hora, sin lanzar otras tareas de ese agente mientras tanto.

#### Scenario: Plan agotado
- **WHEN** `cc` informa el límite de uso con reinicio a las 18:00
- **THEN** la tarea vuelve a `pendiente` con `no_antes_de` 18:00, `intentos` igual y ninguna otra tarea de `cc` arranca antes de las 18:00

#### Scenario: Límite sin hora de reinicio
- **WHEN** el límite llega sin hora de reinicio
- **THEN** `no_antes_de` queda 30 minutos después

#### Scenario: Demasiados límites seguidos
- **WHEN** una tarea vuelve por límite de plan por séptima vez
- **THEN** la tarea pasa a `fallida` con el motivo "límite de plan repetido"

### Requirement: Tiempo máximo y cancelación
Cada intento SHALL tener un tiempo máximo (`timeout_min` de la tarea o del proyecto). Al vencer, o al ejecutar
una cancelación, el orquestador MUST terminar el proceso del agente y todos sus procesos hijos.

#### Scenario: Se acaba el tiempo
- **WHEN** un intento supera su `timeout_min`
- **THEN** el agente y sus hijos terminan, queda un evento `error` de clase `timeout` y la tarea sigue la regla de intentos

#### Scenario: Cancelación con hijos
- **WHEN** se cancela una tarea cuyo agente lanzó un proceso hijo de larga duración
- **THEN** el agente y el hijo terminan y la tarea queda `cancelada`

### Requirement: Procesos sin ventana y atados al orquestador
Los agentes SHALL lanzarse sin ventana y atados al proceso del orquestador, de modo que si el orquestador muere
también mueren los agentes y sus hijos.

#### Scenario: El orquestador muere
- **WHEN** el proceso del orquestador termina de golpe con un agente corriendo
- **THEN** el agente y sus hijos terminan también

### Requirement: Recuperación al reiniciar
Al iniciar, el orquestador SHALL pasar a `pendiente` cada tarea que quedó `en_curso`, con el motivo
"interrumpida", sin sumar `intentos` y sumando `interrupciones`; el siguiente intento retoma la sesión guardada.
Con más de 2 interrupciones la tarea MUST pasar a `fallida`.

#### Scenario: Reinicio con una tarea en curso
- **WHEN** el orquestador se detiene con T-3 `en_curso` y se vuelve a iniciar
- **THEN** T-3 queda `pendiente` con `interrupciones: 1`, sus datos y su historial intactos, y al arrancar retoma la sesión guardada

#### Scenario: Tercera interrupción
- **WHEN** T-3 se interrumpe por tercera vez
- **THEN** T-3 pasa a `fallida` con el motivo "interrumpida demasiadas veces"

#### Scenario: Estado intacto tras reinicio
- **WHEN** el orquestador se reinicia con tareas en todos los estados
- **THEN** todas las tareas que no estaban `en_curso` conservan estado, campos, historial y huella de gate
