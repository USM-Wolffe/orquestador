# Tasks

Tamaño: S (hasta media sesión) o M (una sesión). Cada prueba nueva debe fallar sin el cambio de su tarea. Las
pruebas no usan red ni agentes reales: los agentes se simulan con `pruebas/falsos/agente_falso.py`.

## 1. Seguridad: conectores de claude.ai y MCP no pedidos (parte A, va primero)

- [x] 1.1 (S) Capas de prevención en el lanzamiento de `cc` (design D1):
  Comprobada por: `test_adaptador_cc.PruebaConectoresOperacion.test_capas_con_variable_heredada_y_respaldo`,
  `test_seguridad.PruebaCapasOperacion` (tres capas faltantes y proyecto con `mcp__`) y
  `test_seguridad.PruebaCapasEnElNucleo` (capas fijadas en `seguridad.CAPAS_OBLIGATORIAS`, no en el adaptador).
  - `ENABLE_CLAUDEAI_MCP_SERVERS=false` al final del entorno, aunque venga heredada con otro valor.
  - Perfil con `disableClaudeAiConnectors: true` y `"mcp__*"` en `permissions.deny`, también en el respaldo sin
    `--restricted`.
  - `--disallowedTools mcp__*` en el comando.
  - Capas fijadas por el núcleo en `seguridad.CAPAS_OBLIGATORIAS` y exigidas por `seguridad.revisar_lanzamiento`; un
    agente sin entrada no se lanza.
  - `proyectos.py` rechaza reglas `mcp__` en `permitir_extra` (ya lo hacía el analizador de reglas de E1).

  Verifica: `test_adaptador_cc` revisa comando, perfil y entorno (también con la variable heredada en `true`);
  `test_seguridad` prueba que un adaptador sin una capa no se lanza (clase `seguridad`); una prueba de proyectos
  deja inactivo un proyecto con `permitir_extra: ["mcp__x__y"]`.
- [x] 1.2 (M) Herramientas informadas (design D2):
  Comprobada por: `test_adaptador_cc.PruebaConectoresOperacion` (listas, 60 nombres, sin listas, lista tolerada sin
  `mcp__`, inicio limpio con la matriz), `test_eventos_topes.PruebaTopeInicioOperacion` y
  `test_auditoria.test_matriz_de_cc_en_windows`.
  - `cc.normalizar` emite `herramientas` y `mcp` en `inicio` (o `herramientas: None` si no son listas); hasta 40
    nombres en el evento más `herramientas_omitidas`, con la lista blanca de `eventos.py` al día.
  - Constante de herramientas toleradas de `cc`, vacía, con versión y fecha por nombre.
  - Control "conectores y MCP no declarados" en la matriz de garantías (`duro` en `cc`).
  - El falso emite en `init` lo que recibe en `--tools` y `mcp_servers: []`; guiones `conectores` y
    `mcp_pendiente`.

  Verifica: pruebas del evento `inicio` con listas y con 60 nombres (el evento no pasa el tope), de que la lista
  tolerada no tiene ningún `mcp__` y de la matriz en `inicio`. Las pruebas existentes siguen en verde.
- [x] 1.3 (M) Corte que falla cerrado (design D2):
  Comprobada por: `test_corrida.PruebaHerramientasOperacion` (los cuatro cortes matan al agente y a su hijo en
  menos de 15 s, salida que no se puede revisar, comparación completa, herramienta pedida que falta) y
  `test_planificador.PruebaCorteOperacion` (`fallida` con clase `seguridad`, un solo intento, en los cuatro casos).
  - `herramientas_esperadas` en `Lanzamiento`; en `corrida.py`, comparación al iniciar (sobrantes, `mcp` no vacío,
    aviso sin listas, `tool_use` antes del inicio) y vigilancia de cada `tool_use`.
  - Cierre del Job y `resultado.error` con clase `seguridad`; en `planificador._ejecutar`, esa clase pasa a
    `Desenlace("seguridad")` (`fallida` sin reintentos). La auditoría de git sigue corriendo y `violacion` gana.
  - Guiones `herramienta_tarde` y `sin_init` en el falso.

  Verifica: con `conectores`, `mcp_pendiente`, `herramienta_tarde` y `sin_init`, la tarea queda `fallida` con clase
  `seguridad`, `intentos` no sube de 1, el error nombra las herramientas y no queda ningún proceso vivo. Con un inicio
  limpio, o con una herramienta pedida que falta, la corrida termina `ok`.
- [x] 1.4 (S) Paso 7 "Conectores de claude.ai" en `docs/verificacion-manual.md` (design D3):
  Comprobada por: `test_documentacion.PruebaConectoresDocumentados.test_paso_siete_cinco_capas_y_campos` y
  `test_documentacion.test_verificacion_manual` (paso 6 con `operacion-v1`).
  - Subpasos (a) a (h): comando del hallazgo, cada capa sola, comando completo del adaptador, tarea real y
    `utilization`, con PowerShell y `ConvertFrom-Json` por línea.
  - El paso 6 pasa a validar `operacion-v1`.

  Verifica: `test_documentacion` exige el paso 7 con las cinco capas y los campos `tools` y `mcp_servers`.
- [x] 1.5 (S) **[Sebastian]** Correr el paso 7 con el binario real y anotar el resultado de cada capa. Llenar la
  lista tolerada de `cc` con lo que reporte el comando completo y anotar la escala de `utilization`.

  Hecho el 23-10-2026 con Claude Code 2.1.306 (`verificar_op1.py`, `informe_op1.json`): sin capas, 49 herramientas `mcp__` y 7 servidores; `--strict-mcp-config` solo, la variable sola y `disableClaudeAiConnectors` desde `--settings` solo dejan 0 y 0; `--disallowedTools` y `deny` solos quitan las herramientas pero dejan los 7 servidores conectados; el comando completo del adaptador da 0 y 0, con `tools` = Bash, Edit, Glob, Grep, Read, Skill y Write (pedido menos TodoWrite, sin herramientas propias). La lista tolerada queda vacía. `utilization` llegó en escala 0..1 (0,85, `allowed_warning`).

  Verifica: una tarea real de `cc` llega a `fin` sin error de seguridad y su `inicio` no trae ningún `mcp__`.

## 2. Datos del tablero (parte B)

- [x] 2.1 (S) Campos opcionales en `entrada.py` (spec registro-tareas):
  Comprobada por: `test_entrada.PruebaExplicacionYRevisa` (explicación válida e inválida, revisión válida con
  dependencia automática, revisión de otro cambio, inexistente y a sí misma).
  - `explicacion`: hasta 300 caracteres, sin control ni saltos de línea.
  - `revisa`: tarea existente del mismo proyecto y cambio, distinta de sí misma, agregada a las dependencias.

  Verifica: pruebas de `test_entrada` para el caso válido, la explicación inválida, la revisión de otro cambio y la
  dependencia automática.
- [x] 2.2 (S) Uso del plan (design D5):
  Comprobada por: `test_adaptador_cc.PruebaUsoPlan` (guion `uso_plan`, sin eventos, escala 62/0,62/250) y
  `test_planificador.PruebaUsoPlanGuardado` (el valor queda en `agentes.json`; sin eventos queda `null`).
  - `cc` lee `utilization` y `resetsAt` de todo `rate_limit_event`, normaliza a 0..1 o `null` y lo deja en
    `Resultado.uso_plan`.
  - El planificador guarda el último valor por agente en `agentes.json`.

  Verifica: con el guion `uso_plan`, el valor queda en `agentes.json`; sin eventos queda `null`; 62 da 0,62 y 250
  da `null`.
- [x] 2.3 (M) `orquestador/frases.py` (design D6): eventos a frases, estados de estación en texto y frases de error
  Comprobada por: `test_frases` (frases comunes, mensajes fuera, negaciones siempre, repeticiones juntas,
  frases de error y textos de estación de la spec).
  por clase; junta repeticiones, deja fuera los mensajes y muestra siempre las negaciones.

  Verifica: pruebas unitarias con los escenarios de las specs ("Te espera", "Espera a T-2", "Espera a la anterior",
  "Trabajando, 12 min", "Editó orquestador/tablero.py (2 veces)", "Intentó git push y se le negó", "Se detuvo por
  seguridad").
- [x] 2.4 (M) `vistas.tablero()` y `GET /api/tablero` (design D4):
  Comprobada por: `test_vistas_tablero` (turno con revisión y evidencia, veredictos, agentes, plan topológico,
  sin prompt) y `test_tablero.PruebaApiTablero` (API completa, 401 sin sesión, título con HTML como texto).
  - Turno con explicación, evidencia y revisión (veredicto de la primera línea del informe).
  - Agentes con frase, consumo del día y plan.
  - Plan con orden topológico, "N de M listas", nota y cambios de las últimas 24 horas.
  - Redacción y sin prompt.

  Verifica: pruebas de cada sección, del veredicto (`con reparos`, sin veredicto), de que el texto del prompt no
  aparece en la respuesta y de 401 sin sesión.

## 3. Página del tablero (parte B)

- [x] 3.1 (M) `tablero.html` y `app.css` según `C:\work\orquestador-diseno\tablero_maqueta_v1.html` (design D7):
  Comprobada por: `test_tablero.PruebaDefensas.test_estaticos_sin_codigo_en_linea` y
  `test_paginas_sin_scripts_en_linea` (HTML y CSS servidos, sin nada en línea ni fuentes externas).
  - Barra, "Te toca decidir", "Ahora mismo", "El plan" con leyenda y panel lateral.
  - Clases por agente y por estado en lugar de `style`, `<meter>` para el plan, Bahnschrift y Segoe UI, y
    `consumo.html` con el CSS nuevo.

  Verifica: una prueba lee los HTML y el CSS servidos y no encuentra `<script>` sin `src`, `<style>`, atributos
  `style` ni `on*`, `javascript:`, `@font-face` ni `url(` hacia fuera.
- [x] 3.2 (M) `app.js` y rutas del tablero:
  Comprobada por: `test_tablero.PruebaDefensas` (estáticos sin sesión y página 401 fija), `test_detalle_ya_no_existe`,
  la batería `PruebaSoloLectura.test_bateria_de_peticiones`, `test_tablero.PruebaApiTablero` y las pruebas del
  gate existentes en `test_gates`.
  - Pintado solo con `textContent`, polling cada 3 s, selector de proyecto y panel (Escape, la × o clic fuera).
  - Bitácora del panel, detalles técnicos plegados y gate con código sin cambios.
  - Rutas: `/` sirve `tablero.html`, `/detalle` se elimina, `/static/*` funciona sin sesión y `/` sin sesión da 401
    con la página fija.
  - Docs: `LEEME.md` ("Arranque" y "Aprobar un gate") y el paso 4 de `docs/verificacion-manual.md` con los textos
    nuevos.

  Verifica: pruebas de rutas y de la página 401 sin datos; `app.js` sin `innerHTML`, `eval` ni `new Function`; la
  batería de solo lectura sigue igual y las pruebas del gate (`preparar` y `confirmar`) siguen pasando.

## 4. Acceso fácil (parte C)

- [x] 4.1 (M) Entradas en `tablero.py` (design D8):
  Comprobada por: `test_acceso.PruebaEntradas` (canje, vencido con reloj inyectado, anulado, cierre de sesiones),
  `test_acceso.PruebaEntradasEnElTablero` (aviso sin token ni cookie, cierre desde el tablero, cookie sin
  vencimiento) y `test_tablero.test_nada_en_disco`.
  - Un solo token vigente, que vence a los 5 minutos y se anula al generar otro.
  - Cierre de todas las sesiones a pedido; cookie sin `Max-Age` ni `Expires`.
  - Aviso de sesión nueva en la terminal, sin token ni cookie.

  Verifica: pruebas del enlace vencido (reloj inyectado), del enlace anulado, del canje, del cierre de sesiones y
  del aviso, que no contiene el token. La prueba existente de "nada en disco" sigue pasando.
- [x] 4.2 (M) Terminal, `--abrir` y `orq abrir` (`orquestador/acceso.py` y `orq.py`):
  Comprobada por: `test_acceso.PruebaTerminal` (entrada falsa, navegador simulado, sin TTY, sin tuberías),
  `test_acceso.PruebaOrqAbrir` (candado vivo, abandonado y detenido sin escribir, puerto en el candado,
  `--abrir` con `--sin-tablero`).
  - Hilo que lee la entrada estándar solo con TTY: Enter da un enlace y abre el navegador; `x` y Enter cierra las
    sesiones. Sin TTY avisa una vez.
  - El candado guarda el `puerto` del tablero.
  - `--abrir` es incompatible con `--sin-tablero`; con el candado ocupado hace lo de `orq abrir` y termina con 1.
  - `orq abrir` lee el candado y abre `/` sin token, sin escribir nada.

  Verifica: pruebas con entrada estándar falsa y `webbrowser.open` simulado; `orq abrir` con el candado vivo y
  abandonado; ninguna ruta salvo `/entrar` toca los tokens y el código no crea tuberías con nombre.
- [x] 4.3 (S) Generador de `Orquestador.cmd` en `orquestador/acceso.py` (design D9):
  Comprobada por: `test_acceso.PruebaAccesoDirecto` (ejecución real con `cmd.exe` en `José Pérez` con espacios,
  rutas con variables, rechazo de rutas peligrosas, `.cmd` ajeno e idempotencia, sin inicio automático).
  - Plantilla con marca, rutas con `%USERPROFILE%` o `%LOCALAPPDATA%` cuando calzan, UTF-8 con `chcp 65001` si no,
    y rechazo de `%`, `"`, `!`, `^` y saltos de línea.
  - Escritorio con `SHGetKnownFolderPath` y respaldo `%USERPROFILE%\Desktop`.

  Verifica: una prueba ejecuta el `.cmd` generado con `cmd.exe` en una carpeta temporal `José Pérez` con espacios
  y un `orq.py` falso que anota sus argumentos (`correr --abrir`). Otra confirma que no se escribe nada en Inicio,
  en el registro `Run` ni en el Programador de tareas.

## 5. Instalar en otro PC (parte D)

- [x] 5.1 (M) Detección en `orquestador/instalar.py` (design D10):
  Comprobada por: `test_instalar.PruebaDeteccion` (codex alto/empate, cursor, git ausente, claude sin sesión,
  sin leer credenciales con `open` ni con `pathlib`, entorno filtrado en cada ejecución) y
  `test_instalar.PruebaEjecucionDeSesion` (salida a `DEVNULL`; un agente que no responde no rompe `instalar`).
  - Rutas conocidas sin el `PATH`, `--version` con 10 s como máximo y codex con la versión más alta (en empate, la
    carpeta más reciente). Cursor solo por existencia.
  - Sesión de claude y de codex solo por el código de salida, con la salida a `DEVNULL` y el entorno filtrado.

  Verifica: pruebas con rutas temporales y falsos (dos codex, claude sin sesión, git ausente), más una que registra
  cada archivo abierto durante la detección y no encuentra nada bajo `~/.claude`, `~/.codex`, `~/.cursor` ni
  `~/.ssh`.
- [x] 5.2 (M) `orq instalar [--aplicar]` y aviso del remoto:
  Comprobada por: `test_instalar.PruebaInstalarEscrituras` (simulación, idempotencia, config/cmd ajenos, no-push,
  aviso, sin remoto `origin` no avisa) y `test_instalar.PruebaOrqInstalar`.
  - Plan de pasos y escrituras idempotentes: raíz, `config.json` desde el ejemplo con `json`, carpeta de Cowork y
    acceso directo.
  - `pushurl` en modo lectura, lista numerada de pendientes y aviso en el arranque de `orq correr`.

  Verifica: la simulación no escribe; un segundo `--aplicar` no cambia contenido ni fecha; un `config.json`
  existente queda intacto con su pendiente; un `.cmd` ajeno queda intacto; aparece el pendiente `no-push`; y
  `orq correr` muestra el aviso con un repo de prueba sin `pushurl`.
- [x] 5.3 (S) `docs/INSTALAR.md` (design D12), enlazado desde `LEEME.md`: requisitos, política de ejecución, llave y
  clonado, `no-push`, `instalar` y `--aplicar`, sesiones, proyecto y Cowork, verificación, publicar con la URL
  completa y vuelta atrás.
  Comprobada por: `test_instalar.PruebaGuiaInstalar.test_guia_al_dia` y
  `test_documentacion.PruebaDocumentacion.test_leeme_documenta_comandos_y_cowork`.

  Verifica: `test_documentacion` comprueba que cada `orq …` de la guía existe en el parser y que la guía menciona
  `--aplicar`, `no-push`, `openspec.cmd` y `Get-ExecutionPolicy`.

## 6. Integración

- [x] 6.1 (S) Suite completa sin red, `openspec.cmd validate operacion-v1 --strict` y `pruebas/COBERTURA.md` con cada
  escenario nuevo apuntando a su prueba.
  Comprobada por: suite `unittest discover -s pruebas`, `openspec.cmd validate operacion-v1 --strict` y las
  secciones B/C/D de `pruebas/COBERTURA.md`.

  Verifica: `py -3.12 -m unittest discover -s pruebas` en verde, la validación sin errores y ningún escenario sin
  prueba en `COBERTURA.md`.

## Workflow follow-up

- Sebastian corre los pasos 4 y 7 de `docs/verificacion-manual.md` en el navegador y con el binario real, y compara
  el tablero con la maqueta.
- Sebastian borra `orquestador/estaticos/kanban.html` y `detalle.html` (CLAUDE.md impide al agente borrar fuera de
  `out/`) y hace el commit.
- Antes de crear el repo en GitHub: Sebastian anula el push del remoto y configura la credencial (decisión 32).
- Archivar el change después del gate de Sebastian.
