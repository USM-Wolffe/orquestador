# Spec Delta

## Purpose

Deja el orquestador listo en un PC nuevo a partir del repo privado de Sebastian, sin leer credenciales, sin
tocar git y sin que un agente pueda publicar en GitHub por la vía por defecto.

## ADDED Requirements

### Requirement: orq instalar simula por defecto
`orq instalar` SHALL mostrar lo que haría, paso a paso, sin escribir nada. Solo con `--aplicar` MUST escribir, y
correrlo dos veces seguidas MUST dejar todo igual que correrlo una vez.

#### Scenario: Simulación
- **WHEN** Sebastian corre `orq instalar` en un PC sin raíz de estado
- **THEN** ve cada paso con "crearía" y no se crea ningún archivo ni carpeta

#### Scenario: Idempotencia
- **WHEN** se corre `orq instalar --aplicar` dos veces
- **THEN** la segunda vez todos los pasos dicen "ya estaba" y ningún archivo cambia su contenido ni su fecha de modificación

### Requirement: Detección de herramientas por rutas conocidas
`orq instalar` SHALL buscar Python, git, `claude`, `codex` y el CLI de Cursor solo en rutas conocidas, nunca en el
`PATH`, y confirmar cada uno con `--version` (10 s como máximo). En `codex` MUST elegir la versión más alta entre
`%LOCALAPPDATA%\OpenAI\Codex\bin\*\codex.exe` y, si empatan, la carpeta más reciente.

#### Scenario: Varias versiones de codex
- **WHEN** existen `bin\a1\codex.exe` (0.162.0) y `bin\b2\codex.exe` (0.163.0)
- **THEN** el informe muestra `bin\b2\codex.exe` con 0.163.0

#### Scenario: Cursor presente
- **WHEN** existe `%LOCALAPPDATA%\cursor-agent\agent.ps1`
- **THEN** el informe lo muestra como encontrado, sin ejecutarlo, con la nota "se verifica en E4"

#### Scenario: Herramienta ausente
- **WHEN** no hay `git` en ninguna ruta conocida
- **THEN** el informe lo marca como faltante y lo agrega a los pendientes con la ruta esperada

### Requirement: Sesión de cada agente sin leer credenciales
`orq instalar` SHALL revisar la sesión de `claude` con `auth status` y la de `codex` con `login status`, mirando
solo el código de salida, con la salida descartada sin leerla y el entorno filtrado como el de los agentes. MUST
NOT abrir archivos de credenciales de ningún agente.

#### Scenario: Claude sin sesión
- **WHEN** `claude auth status` termina con código 1
- **THEN** el informe dice "claude: sin sesión" y agrega `claude auth login` a los pendientes

#### Scenario: Sin leer credenciales
- **WHEN** las pruebas corren `orq instalar` con falsos que dejan registro de su entrada
- **THEN** ningún archivo bajo `~/.claude`, `~/.codex`, `~/.cursor` ni `~/.ssh` se abre, y la salida de los falsos no aparece en el informe

### Requirement: Lo que crea la instalación
Con `--aplicar`, `orq instalar` SHALL crear la raíz de estado, `config.json` con las rutas absolutas detectadas
si no existe, la carpeta de Cowork y el acceso directo del escritorio. Un `config.json` existente MUST NOT
modificarse: las diferencias con lo detectado van a los pendientes.

#### Scenario: Config existente
- **WHEN** ya hay `config.json` y su `agentes.cc.ejecutable` difiere de la ruta detectada
- **THEN** el archivo no cambia y el pendiente dice qué clave revisar y cuál es la ruta detectada

#### Scenario: Acceso directo ajeno
- **WHEN** ya existe un `Orquestador.cmd` en el escritorio que no generó el orquestador
- **THEN** no se sobrescribe y queda como pendiente

### Requirement: Lista de pendientes
`orq instalar` SHALL terminar con una lista numerada de lo que queda por hacer a mano, cada punto con el comando
exacto cuando lo hay, y MUST incluir siempre los pasos que nunca automatiza.

#### Scenario: Pendientes fijos
- **WHEN** termina `orq instalar`, con o sin `--aplicar`
- **THEN** la lista incluye conectar `Orquestador-Cowork\<proyecto>` en Cowork, crear un proyecto con `orq proyecto nuevo` y, si el remoto `origin` tiene push habilitado, el comando para anularlo

### Requirement: Remoto sin push por defecto
`orq instalar` y el arranque de `orq correr` SHALL revisar, en modo lectura, si el repo del orquestador tiene la URL
de push de `origin` anulada, y MUST NOT cambiar la configuración de git. La guía de instalación SHALL indicar cómo
anularla y cómo publicar con la URL completa y una credencial que se pida en cada push.

#### Scenario: Push habilitado
- **WHEN** `remote.origin.pushurl` no existe
- **THEN** el pendiente trae `git remote set-url --push origin no-push` para que Sebastian lo corra

#### Scenario: Push anulado
- **WHEN** `remote.origin.pushurl` vale `no-push`
- **THEN** el informe dice "push por defecto anulado" y no agrega pendiente

#### Scenario: Aviso al arrancar
- **WHEN** `orq correr` arranca y el repo del orquestador tiene `origin` sin `pushurl` anulada
- **THEN** la terminal muestra un aviso con el comando para anularla y el orquestador sigue funcionando

### Requirement: Guía de instalación
El repo SHALL traer `docs/INSTALAR.md` con los pasos en PowerShell para un PC nuevo: requisitos, clonar,
`orq instalar` y `--aplicar`, la política de ejecución de PowerShell, la sesión de cada agente, conectar la
carpeta en Cowork, el remoto sin push, cómo publicar y la verificación manual.

#### Scenario: Guía al día
- **WHEN** corre la prueba de documentación
- **THEN** cada comando `orq` que nombra la guía existe en el parser y la guía menciona `--aplicar`, `no-push` y `openspec.cmd`
