# Spec Delta

## Purpose

Permite que una sola instalación del orquestador atienda varios repos, cada uno con su configuración y con su
estado guardado fuera del repo del proyecto.

## ADDED Requirements

### Requirement: Raíz de estado fuera de los repos
El orquestador SHALL guardar todo su estado bajo una raíz de estado configurable (por defecto
`%USERPROFILE%\.orquestador`). Al iniciar MUST negarse a correr si la raíz de estado queda dentro de algún repo
registrado o de alguno de sus worktrees.

#### Scenario: Raíz por defecto
- **WHEN** la configuración global no define `raiz_estado`
- **THEN** el orquestador usa `%USERPROFILE%\.orquestador` y crea ahí `proyectos\`

#### Scenario: Raíz dentro de un repo
- **WHEN** `raiz_estado` apunta a una carpeta dentro del repo de un proyecto registrado
- **THEN** el orquestador termina con un error que nombra el proyecto y no escribe nada

### Requirement: Un proyecto por carpeta
Cada proyecto SHALL tener una carpeta `proyectos\<proyecto>\` bajo la raíz de estado, con un `proyecto.json` que
define al menos el nombre, la ruta del repo, la rama base y los agentes permitidos. El nombre MUST cumplir
`^[a-z0-9][a-z0-9-]{0,60}$` y coincidir con el nombre de la carpeta.

#### Scenario: Proyecto válido
- **WHEN** existe `proyectos\demo\proyecto.json` con nombre `demo`, un repo git existente y `agentes_permitidos: ["cc"]`
- **THEN** el orquestador lista `demo` como proyecto activo

#### Scenario: Nombre que no coincide
- **WHEN** la carpeta es `proyectos\demo\` y el `proyecto.json` dice `"nombre": "otro"`
- **THEN** el orquestador ignora ese proyecto y registra un error de configuración

#### Scenario: Repo inexistente
- **WHEN** la ruta del repo no existe o no es un repo git
- **THEN** el proyecto queda inactivo, el error queda en el registro y los demás proyectos siguen funcionando

### Requirement: Varios proyectos en una instalación
Una instalación SHALL atender a la vez todos los proyectos activos, con estado, sesiones y eventos separados por
proyecto. Una tarea MUST pertenecer a un solo proyecto y sus rutas MUST resolverse solo contra la configuración
de ese proyecto, nunca contra rutas libres que vengan en la tarea.

#### Scenario: Estado separado
- **WHEN** hay tareas en los proyectos `a` y `b`
- **THEN** las tareas de `a` quedan en `proyectos\a\tareas.json` y las de `b` en `proyectos\b\tareas.json`

#### Scenario: Ruta libre en una tarea
- **WHEN** una solicitud de Cowork trae un campo con una ruta de repo distinta de la del proyecto
- **THEN** la solicitud se rechaza con un error de validación

### Requirement: Límites del proyecto solo restringen
La configuración de un proyecto SHALL poder bajar, pero no subir, los límites de paralelismo globales y por
agente, y MUST poder agregar reglas de denegación pero no quitar las obligatorias de seguridad.

#### Scenario: Límite mayor que el global
- **WHEN** el global para `cc` es 1 y el proyecto pide 3
- **THEN** el orquestador usa 1 para ese proyecto y registra una advertencia

#### Scenario: Intento de quitar una denegación obligatoria
- **WHEN** el `proyecto.json` intenta permitir `git push`
- **THEN** el proyecto queda inactivo con un error de configuración

### Requirement: Una sola instancia por raíz de estado
El orquestador SHALL tomar un candado exclusivo sobre la raíz de estado al iniciar. Si otra instancia viva tiene
el candado, la nueva MUST terminar sin tocar el estado.

#### Scenario: Segunda instancia
- **WHEN** ya hay un orquestador corriendo con la misma raíz de estado y se inicia otro
- **THEN** el segundo informa que ya hay uno corriendo y termina sin escribir

#### Scenario: Candado abandonado
- **WHEN** el candado existe pero el proceso que lo tomó ya no está vivo
- **THEN** el orquestador nuevo toma el candado y lo deja en el registro
