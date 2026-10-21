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
