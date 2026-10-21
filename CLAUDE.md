# Orquestador multiagente

Herramienta genérica, sin relación con ningún cliente: una sesión de Claude (Cowork) gestiona un proyecto
de software, lo divide en tareas y las entrega a agentes de código (Claude Code, Codex CLI, Cursor CLI) que
trabajan sin ventana en worktrees de git. El humano (Sebastian) aprueba en los gates y hace los commits.
Punto de partida: `puente.py` (v0, solo Claude Code); ver `LEEME.md`. Decisión de origen: R-38 del
proyecto Embudo de Riesgo (21-10-2026).

## Reglas
- Windows 11, Python 3.12 (`py -3.12`). Preferir la librería estándar; toda dependencia nueva se justifica.
- Ciclo OpenSpec: proposal → gate de Sebastian → apply → validate → gate → commit (lo hace Sebastian) → archive.
- No hagas git commit, push, reset, checkout ni merge. No borres archivos fuera de `out/`.
- Seguridad, que no se negocia: ningún agente corre con bypass de permisos; commit, push y lectura de
  credenciales (`~/.embudo`, `~/.ssh`, archivos `.env`) bloqueados en cada agente; el orquestador nunca
  ejecuta comandos que vengan dentro de una tarea, solo le pasa el prompt al agente.
- Toda lógica nueva trae su prueba (que falla sin el cambio). Pruebas sin red y sin agentes reales: los
  agentes se simulan con ejecutables falsos.
- Nada de datos de clientes en este repo: fixtures sintéticos.
- Español de Chile en textos, mensajes y comentarios.
