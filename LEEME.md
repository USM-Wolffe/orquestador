# Puente Claude (Cowork) ↔ Claude Code

Claude deja trabajos en `trabajos/pendientes/`. El puente los corre de a uno con Claude Code sin ventana
(`claude -p`), en el worktree del cambio (`..\wt-<cambio>`, lo crea si no existe), retomando la sesión de
Claude Code de ese cambio (`sesiones.json`). La respuesta queda en `trabajos/hechos/<id>.md` y los datos
de la corrida en `<id>.resultado.json`. `estado.json` dice si el puente está vivo; `registro.log`, qué hizo.

## Seguridad
- Claude Code corre con `dontAsk` y la lista fija de `config.json`: lo que no está en `permitir` se niega
  solo. Nunca `bypassPermissions`. Commit, push, reset, checkout, merge, rm -rf, terraform apply y aws
  están denegados. No puede leer `.embudo` (credenciales); el código del embudo sí las usa al llamar a la API.
- El puente no ejecuta comandos del trabajo: solo le pasa el prompt a Claude Code.
- Acciones de git (commit, archive, merge a main): apagadas (`permitir_git: false`). Si las enciendes,
  Claude solo deja ese trabajo después de tu OK en el chat.

## Uso
Procesar lo pendiente y terminar:

    py -3.12 puente.py --una-vez

Dejarlo corriendo mientras trabajas (revisa cada 20 s; se detiene con Ctrl+C o cerrando la ventana):

    py -3.12 puente.py

Que parta solo al iniciar sesión es decisión tuya; Claude no lo instala.

---

# Orquestador v1 (E1)

Un solo proceso, `orq correr`, toma las tareas que deja Cowork, las corre con Claude Code (`cc`) sin ventana en un
worktree por cambio y muestra todo en un tablero local. Sebastian aprueba los gates con un botón del tablero más un
código que solo aparece en la terminal, y hace los commits a mano. El puente v0 sigue funcionando igual.

Requisitos: Windows 11, Python 3.12 (`py -3.12`), git y Claude Code. Solo librería estándar.

## Instalación

1. Crea la raíz de estado y copia el ejemplo de configuración (rutas absolutas: nunca se busca en el `PATH`):

       New-Item -ItemType Directory -Force "$env:USERPROFILE\.orquestador" | Out-Null
       Copy-Item .\ejemplos\config.example.json "$env:USERPROFILE\.orquestador\config.json"

   Revisa en `config.json` las rutas de `agentes.cc.ejecutable` (por ejemplo
   `%USERPROFILE%\.local\bin\claude.exe`) y de `herramientas.git` (por ejemplo
   `C:\Program Files\Git\cmd\git.exe`).
2. Crea un proyecto con valores seguros (gate por defecto, sin red, sin variables extra):

       py -3.12 .\orq.py proyecto nuevo demo --repo C:\ruta\al\repo-demo

   `ejemplos\proyecto.example.json` muestra todas las claves de `proyecto.json`.

## Arranque

    py -3.12 .\orq.py correr

La terminal muestra el enlace del tablero (`http://127.0.0.1:8765/entrar?t=…`). Sirve una sola vez: ábrelo en el
navegador y queda una sesión que dura hasta reiniciar `orq correr`. Opciones:
- `--sin-tablero`: solo el bucle, sin abrir ningún puerto.
- `--una-vez`: procesa un ciclo y termina.
- `--permitir-codigo-modificado`: deja usar los gates aunque `orquestador\` u `orq.py` tengan cambios sin commit
  (si no, los gates quedan deshabilitados y el tablero lo avisa). Cada decisión queda marcada en el historial.

## Cowork

En la app de Cowork conecta **solo** `%USERPROFILE%\Orquestador-Cowork\<proyecto>` (por ejemplo
`Orquestador-Cowork\demo`), con `entrada\`, `respuestas\` y `salida\`. Nunca conectes `%USERPROFILE%\.orquestador`.
Cowork deja solicitudes en `entrada\`, lee los acuses en `respuestas\` y el estado en `salida\` (`estado.json`,
`eventos-recientes.json`, `consumo.json`, `resultados\` y `diffstat\`), sin secretos ni prompts completos.

## Aprobar un gate

1. Abre la tarea en `esperando_gate` desde el tablero: revisa el diff stat, el informe y la huella corta.
2. Pulsa **Aprobar** (o **Rechazar con nota**). La terminal de `orq correr` muestra un código de 6 dígitos.
3. Escribe el código en el tablero y pulsa **Confirmar** antes de 120 segundos.

Si el worktree cambia después de revisar, la decisión se rechaza ("el estado cambió, vuelve a revisar"). Tres
códigos erróneos bloquean los gates hasta reiniciar `orq correr`. El commit lo sigues haciendo tú.

## Otros comandos

    py -3.12 .\orq.py estado
    py -3.12 .\orq.py tarea demo T-1 reintentar
    py -3.12 .\orq.py tarea demo T-1 cancelar
    py -3.12 .\orq.py proyecto lista
    py -3.12 .\orq.py importar-v0 --desde C:\ruta\al\puente-v0 --proyecto demo
    py -3.12 .\orq.py importar-v0 --desde C:\ruta\al\puente-v0 --proyecto demo --aplicar

`importar-v0` solo muestra lo que haría hasta que le pasas `--aplicar`, y nunca modifica la carpeta del v0.
Todos los comandos responden a `--help`.

## Pruebas y verificación

    py -3.12 -m unittest discover -s pruebas
    openspec.cmd validate orquestador-v1 --strict

Las pruebas no usan red (solo 127.0.0.1 para el tablero) ni el `claude` real: usan `pruebas\falsos\agente_falso.py`.
Lo que solo se puede probar con el binario real está en `docs\verificacion-manual.md`.
