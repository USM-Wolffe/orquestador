# Instalar el orquestador en un PC nuevo

Guía en PowerShell. El orquestador no lee credenciales, no toca la configuración de git y no cambia la
política de ejecución. Tras clonar, `orq instalar` simula el plan; solo con `--aplicar` escribe lo que falta.

## 1. Requisitos

- Windows 11
- Python 3.12 con el lanzador `py` (`py -3.12 --version`)
- Git for Windows
- Claude Code nativo (`claude.exe`); Codex y Cursor son opcionales (E2 y E4)

## 2. Política de ejecución de PowerShell

Revisa sin cambiar nada:

    Get-ExecutionPolicy -List

Los `.ps1` pueden estar bloqueados: no hace falta cambiarlo para el orquestador. Se usan `openspec.cmd`, `py` y el
`.cmd` del escritorio. `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` queda para cuando se active Cursor (E4).

## 3. Llave de despliegue y clonado

Los agentes corren con tu usuario: lo único que les impide publicar es que el push pida algo que solo tú tecleas.

1. Crea una llave solo para este repo, con frase de paso:

       ssh-keygen -t ed25519 -f "$env:USERPROFILE\.ssh\orquestador_deploy" -C "orquestador deploy"

2. En GitHub, en *Settings → Deploy keys* del repo, agrega `orquestador_deploy.pub` con escritura. No la agregues
   a tu cuenta: así solo sirve para este repo.
3. No la cargues en un agente SSH. No corras `ssh-add` con ella y revisa que el servicio esté detenido:

       Get-Service ssh-agent

   Debe decir `Stopped` (o no existir). Si `ssh-add -l` muestra la llave, quítala con `ssh-add -d`.
4. No guardes un token de GitHub en el Administrador de credenciales para este repo (no clones por HTTPS con
   usuario y token).

Clona con esa llave y anula el push por defecto:

    git -c core.sshCommand="ssh -i ~/.ssh/orquestador_deploy -o IdentitiesOnly=yes" clone git@github.com:<usuario>/orquestador.git
    cd orquestador
    git remote set-url --push origin no-push

Para publicar más adelante, ver el paso 8.

## 4. `orq instalar`

Simulación (no escribe nada):

    py -3.12 .\orq.py instalar

Si el plan se ve bien:

    py -3.12 .\orq.py instalar --aplicar

Eso crea, si faltan: `%USERPROFILE%\.orquestador`, `config.json` (desde el ejemplo, con las rutas detectadas),
`%USERPROFILE%\Orquestador-Cowork` y `Orquestador.cmd` en el escritorio. No pisa un `config.json` ni un `.cmd`
ajenos. Si el remoto aún acepta push, el pendiente incluye `git remote set-url --push origin no-push`.

## 5. Sesiones de los agentes

    claude auth login

Si vas a usar Codex en E2: `codex login`. Cursor se verifica en E4.

## 6. Proyecto y Cowork

    py -3.12 .\orq.py proyecto nuevo <nombre> --repo <ruta-absoluta-del-repo>

En la app de Cowork conecta **solo** `Orquestador-Cowork\<proyecto>` (por ejemplo `Orquestador-Cowork\demo`).
Nunca conectes `%USERPROFILE%\.orquestador`.

## 7. Verificación

Sigue `docs/verificacion-manual.md`, pasos 1 a 7. Para validar el change OpenSpec:

    openspec.cmd validate operacion-v1 --strict

## 8. Publicar

Con la pushurl en `no-push`, publica con la URL completa y la llave del repo; te pedirá la frase de paso:

    git -c core.sshCommand="ssh -i ~/.ssh/orquestador_deploy -o IdentitiesOnly=yes" push git@github.com:<usuario>/orquestador.git main

No le quites la frase a la llave ni la cargues en un agente SSH: cualquier proceso con tu usuario podría publicar.

## 9. Vuelta atrás

Puedes borrar a mano, sin dejar el orquestador a medias:

- `%USERPROFILE%\.orquestador` (raíz de estado)
- `%USERPROFILE%\Orquestador-Cowork`
- `Orquestador.cmd` en el escritorio (solo si lo generó el orquestador; la primera línea es
  `rem orq-acceso-directo v1 …`)
- El clon del repo, si ya no lo necesitas

No hay entradas en Inicio, en el registro `Run` ni en el Programador de tareas.
