# seguridad-agentes Specification

## Purpose
Fija los controles de seguridad que se aplican a cada agente sin excepción, cómo se verifican antes y después de
cada corrida, y cómo se declara con honestidad qué tan fuerte es cada control. En esta etapa cubre a Claude Code
(`cc`); los demás agentes se suman en sus etapas.

## Requirements

### Requirement: Ningún comando con bypass de permisos
Antes de lanzar un agente, el orquestador SHALL revisar el comando completo contra la lista de banderas y valores
prohibidos de ese agente y MUST negarse a lanzarlo si aparece alguno, dejando la tarea con un error de clase
`seguridad`. La revisión MUST ocurrir aunque el adaptador sea el que armó el comando.

#### Scenario: Comandos de cc
- **WHEN** se arman los comandos de `cc` para todas las combinaciones de sesión nueva o retomada y red sí o no
- **THEN** ninguno contiene `--dangerously-skip-permissions`, `--allow-dangerously-skip-permissions`, `bypassPermissions` ni `--permission-mode auto`

#### Scenario: Adaptador defectuoso
- **WHEN** un adaptador de prueba devuelve un comando con `--dangerously-skip-permissions`
- **THEN** el orquestador no lanza el proceso y la tarea registra un error de clase `seguridad`

### Requirement: Perfil de permisos fijado por el orquestador
En cada corrida el orquestador SHALL entregarle al agente su perfil de permisos generado desde la configuración
del proyecto, y MUST neutralizar la configuración del usuario y la del repo que pueda ampliar permisos, agregar
hooks o cambiar el modo de aprobación, por los medios que el agente ofrezca.

#### Scenario: Repo con settings propios
- **WHEN** el worktree trae un `.claude/settings.json` con un hook o una regla `allow` de `git push`
- **THEN** la corrida de `cc` no carga ese archivo (`--restricted`) y el perfil lleva `disableAllHooks: true` y `disableBypassPermissionsMode: "disable"`

### Requirement: Denegaciones obligatorias
Todo perfil SHALL denegar `git commit`, `push`, `reset`, `checkout`, `switch`, `restore`, `stash`, `merge`,
`rebase`, `clean`, `branch -d/-D`, `worktree remove` y `git -C`; leer o escribir `~/.embudo`, `~/.ssh`, `.env`,
`.env.*`, la raíz de estado, la carpeta de Cowork y las credenciales de los agentes; escribir fuera del worktree;
y la red, incluido el puerto del tablero, si la tarea no la pide.

#### Scenario: Perfil generado de cc
- **WHEN** se genera el perfil de `cc` para cualquier proyecto
- **THEN** contiene esas denegaciones como reglas `Bash(...)`, `PowerShell(...)`, `Read(...)` y `Edit(...)`, incluidas las rutas absolutas de la raíz de estado y de la carpeta de Cowork

#### Scenario: Red apagada por defecto
- **WHEN** una tarea no trae `red` o trae `red: false`
- **THEN** `WebFetch` y `WebSearch` no están en `--tools`, y `curl`, `wget`, `Invoke-WebRequest` e `Invoke-RestMethod` están negados

### Requirement: Nivel de garantía declarado
El orquestador SHALL tener una matriz fija que diga, por agente, plataforma y control, si el control es
`duro`, `sandbox` o `instruccion`. Cada evento `inicio` MUST incluir los niveles de esa corrida y el tablero
MUST mostrarlos en el detalle de la tarea.

#### Scenario: Claude Code en Windows nativo
- **WHEN** arranca una tarea de `cc` en Windows sin WSL
- **THEN** el evento `inicio` declara `instruccion` para git, credenciales, escritura fuera del worktree y red, y `duro` para el bypass de permisos

### Requirement: Worktree sin secretos
Antes de cada corrida, el orquestador SHALL revisar el worktree y MUST negarse a lanzar el agente si encuentra
`.env`, `.env.*` (salvo `.env.example`), `id_rsa*`, `*.pem`, `*.pfx` o `*.p12` fuera de `.git`; la tarea queda con
error de clase `seguridad` y la lista de rutas, nunca su contenido.

#### Scenario: Alguien copió un .env al worktree
- **WHEN** existe `wt-login\.env`
- **THEN** el agente no se lanza y el error nombra `.env` sin mostrar su contenido

### Requirement: Skills del repo que conceden permisos
Antes de lanzar `cc`, el orquestador SHALL buscar en el worktree skills versionadas (`.claude/skills/*/SKILL.md`)
cuyo frontmatter traiga `allowed-tools` o `hooks`, y MUST negarse a lanzar si alguna no está en las huellas
aprobadas del proyecto, porque Claude Code concede esos permisos incluso en `-p` sin confianza.

#### Scenario: Skill con allowed-tools sin aprobar
- **WHEN** el worktree trae `.claude/skills/x/SKILL.md` con `allowed-tools` y su huella SHA-256 no está aprobada
- **THEN** la tarea de `cc` no se lanza y queda con error de clase `seguridad` que nombra la skill

#### Scenario: Skill aprobada
- **WHEN** la huella de esa skill está en `huellas_aprobadas` del proyecto
- **THEN** la tarea se lanza normalmente

### Requirement: Entorno filtrado
El proceso del agente SHALL recibir un entorno sin variables cuyo nombre calce con patrones de secreto (`*KEY*`,
`*TOKEN*`, `*SECRET*`, `*PASSWORD*`, `AWS_*`, `EMBUDO_*`, `GH_*`, `GITHUB_*`), salvo las que el proyecto permita de
forma explícita. Para `cc` MUST quitarse `ANTHROPIC_API_KEY` salvo que el proyecto pida facturar por API.

#### Scenario: Variable con secreto
- **WHEN** el orquestador corre con `AWS_SECRET_ACCESS_KEY` y `EMBUDO_TOKEN` en su entorno
- **THEN** el agente lanzado no recibe ninguna de las dos

#### Scenario: Suscripción en vez de API
- **WHEN** el entorno tiene `ANTHROPIC_API_KEY` y el proyecto no pide API
- **THEN** `cc` corre sin esa variable y con `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1`

### Requirement: Auditoría de git después de cada corrida
El orquestador SHALL tomar una foto del repo antes y después de cada corrida (HEAD y su rama, todas las refs,
reflog de HEAD y de la rama, stash, lista de worktrees y huella de `.git/config` y `.git/hooks`). Si algo
cambió, la tarea MUST pasar a `fallida` con error de clase `violacion`, sin revertir nada y avisando en el tablero.

#### Scenario: El agente hizo un commit
- **WHEN** después de la corrida el HEAD de la rama del cambio es distinto al de antes
- **THEN** la tarea queda `fallida` con clase `violacion`, el evento `error` nombra la ref que cambió y el tablero lo destaca

#### Scenario: Corrida limpia
- **WHEN** la corrida solo cambió archivos del worktree
- **THEN** la auditoría no reporta nada y la tarea sigue su curso normal

### Requirement: El orquestador no ejecuta lo que trae una tarea
El orquestador SHALL entregarle el prompt al agente solo por la entrada estándar y MUST NOT ejecutar comandos ni
interpolar en el comando texto libre de la tarea; en el comando solo entran valores validados por expresión
regular (id de sesión, nombre de cambio y rama) y rutas de la configuración.

#### Scenario: Prompt con comandos
- **WHEN** el prompt contiene `"; git push origin main` y `$(rm -rf .)`
- **THEN** ese texto llega solo por la entrada estándar del agente y no aparece en el comando lanzado

#### Scenario: Id de sesión malicioso
- **WHEN** el registro de sesiones tiene un id con espacios o comillas
- **THEN** el orquestador no lo usa, abre una sesión nueva y registra un error
