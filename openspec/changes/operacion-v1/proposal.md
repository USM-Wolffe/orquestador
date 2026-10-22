# Proposal

## Why

La E1 quedó en `main` (803909a) y Sebastian corrió la verificación manual completa. De esa prueba salieron cuatro
pedidos. El más urgente es de seguridad: `claude -p --restricted --tools "Read"` (sin `--strict-mcp-config`)
mostró en `system/init.tools` los conectores de claude.ai de Sebastian (`mcp__claude_ai_*`: Google Drive con
`share_file` y `trash_file`, Canva, Gamma, Claude Docs y Fireflies). Un agente podría usar su cuenta. Los otros
tres son de operación: el tablero cuesta leerlo, abrirlo es incómodo y no hay forma de instalar el orquestador
en otro PC.

## What Changes

- **A. Conectores apagados y comprobados (seguridad, va primero)**:
  - Prevención en cada corrida de `cc`, solo con lo que la documentación oficial respalda:
    - `ENABLE_CLAUDEAI_MCP_SERVERS=false` en el entorno del agente.
    - `disableClaudeAiConnectors: true` y `"mcp__*"` en `permissions.deny` del perfil.
    - `--disallowedTools "mcp__*"` en el comando; se mantiene `--strict-mcp-config`.
    - El orquestador no lanza un comando de `cc` al que le falte alguna de estas capas, y un proyecto no puede
      abrir reglas `mcp__` en `permitir_extra`.
  - Comprobación que falla cerrada: si `system/init` trae una herramienta que no se pidió (ni está en la lista
    tolerada y verificada), algún servidor MCP, o no llega antes de la primera acción, o si el agente pide una
    herramienta fuera de lo comprobado, el orquestador corta la corrida. La tarea queda `fallida` con clase
    `seguridad` y sin reintentos.
  - Paso 7 nuevo en `docs/verificacion-manual.md`, para probar cada capa por separado con el binario real.
- **B. Tablero rediseñado** según la maqueta aprobada (`tablero_maqueta_v1.html`):
  - "Te toca decidir", "Ahora mismo" y "El plan" (cambios como líneas y tareas como estaciones), más un panel
    lateral de detalle.
  - Textos en lenguaje simple y una bitácora que traduce los eventos a frases.
  - Una sola llamada `GET /api/tablero` con los datos que faltaban: qué se aprueba, resumen de la revisión, frase
    de la última acción y consumo del día (uso del plan solo si Claude Code lo informa).
  - Se mantienen la CSP `default-src 'none'`, los estáticos sin nada en línea, las fuentes del sistema, la API de
    solo lectura y el gate con código.
  - **BREAKING (interfaz)**: desaparecen el kanban por columnas y el filtro por agente.
- **C. Acceso fácil**:
  - `orq correr --abrir` abre el navegador ya con la sesión.
  - Enter en la ventana del orquestador da un enlace nuevo de un solo uso (vence a los 5 minutos) y abre el
    navegador; `x` y Enter cierra todas las sesiones.
  - `orq abrir` abre el tablero **sin token** y, si no hay sesión, explica el Enter. Es una desviación de lo pedido:
    cualquier vía por la que un segundo proceso pida un enlace la puede usar también un agente (design D8).
  - Acceso directo `Orquestador.cmd` en el escritorio. Arrancar con Windows queda fuera: lo decide Sebastian.
- **D. Instalar en otro PC**:
  - `orq instalar`, idempotente y en simulación salvo `--aplicar`:
    - Detecta Python, git, claude, codex (la versión más alta) y Cursor, por rutas conocidas.
    - Revisa la sesión de cada agente solo por el código de salida.
    - Crea la raíz de estado, la config, la carpeta de Cowork y el acceso directo.
    - Lista lo pendiente.
  - `docs/INSTALAR.md` con los pasos en PowerShell.
  - El remoto de GitHub queda sin push por defecto (URL de push anulada), `orq correr` avisa si no lo está y
    Sebastian publica con la URL completa y una llave con frase de paso.

## Capabilities

### New Capabilities
- `acceso-tablero`: acceso directo del escritorio, apertura del navegador, enlace nuevo desde la terminal y
  `orq abrir`.
- `instalacion`: `orq instalar`, la guía `docs/INSTALAR.md` y el remoto sin push por defecto.

### Modified Capabilities
- `seguridad-agentes`: conectores de claude.ai y servidores MCP no declarados apagados, con comprobación que falla
  cerrada al iniciar y vigilancia durante la corrida.
- `adaptadores-agente`: comando y perfil de `cc` con las capas nuevas, herramientas informadas al iniciar y uso del
  plan.
- `tablero`: página principal en tres partes con panel de detalle en lugar del kanban, lenguaje simple, bitácora en
  frases, API de la vista, enlaces de entrada con vencimiento y aclaración de que el servidor HTTP no lanza
  procesos.
- `registro-tareas`: campos opcionales `explicacion` y `revisa` en la tarea.

## Impact

- **Código**:
  - `orquestador/adaptadores/cc.py` y `base.py`, `corrida.py`, `planificador.py`, `seguridad.py`, `proyectos.py`,
    `entrada.py`, `eventos.py`, `vistas.py`, `tablero.py`, `candado.py` y `orq.py`.
  - Nuevos `orquestador/frases.py`, `orquestador/acceso.py` y `orquestador/instalar.py`.
  - Estáticos nuevos o reescritos: `tablero.html`, `app.css` y `app.js`.
  - Pruebas: `pruebas/falsos/agente_falso.py` emite las herramientas pedidas y `mcp_servers`; guiones nuevos.
- **Archivos que Sebastian borra a mano** (CLAUDE.md impide al agente borrar fuera de `out/`):
  `orquestador/estaticos/kanban.html` y `detalle.html`, que dejan de servirse.
- **Dependencias**: ninguna nueva. Solo librería estándar (`ctypes` para la carpeta del escritorio).
- **Sistemas**:
  - `orq instalar --aplicar` escribe en `%USERPROFILE%\.orquestador`, `%USERPROFILE%\Orquestador-Cowork` y el
    escritorio.
  - No toca git, el registro de Windows ni la política de ejecución de PowerShell.
- **Agentes**: hasta que Sebastian corra el paso 7 y llene la lista tolerada, toda tarea de `cc` falla cerrada si
  Claude Code expone herramientas propias que no se pidieron. Es lo esperado.
- **No toca** `puente.py`, el v0 ni `C:\work\Embudo de Riesgo\`.
