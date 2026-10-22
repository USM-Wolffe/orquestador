# Tasks (E1)

Tamaños: **S** = medio día o menos, **M** = alrededor de un día. Cada tarea entra con sus pruebas (`unittest`, sin
red y sin agentes reales), que deben pasar con `py -3.12 -m unittest discover -s pruebas` y fallar si se quita el
cambio.

## 1. Base y configuración

- [x] 1.1 [S] Crear el paquete `orquestador/` y `orq.py` con los subcomandos `correr`, `tarea`, `proyecto`, `estado` e `importar-v0`, y crear `pruebas/ayudantes.py` (raíz de estado y carpeta de Cowork temporales, repo git sintético, conexiones bloqueadas salvo loopback). Verificar que `py -3.12 orq.py --help` lista los subcomandos y que una prueba confirma el bloqueo de red.
  - Pruebas: `pruebas/test_base.py` (7). `PruebaOrqAyuda` cubre `--help` con los cinco subcomandos, el paquete importable y un subcomando pendiente que sale con código 2. `PruebaRedBloqueada` cubre IP pública y nombre de host bloqueados y loopback permitido.
- [x] 1.2 [M] Implementar `config.py` y la carga de proyectos:
  - Raíz de estado y `cowork_raiz` fuera de todo repo y separadas entre sí.
  - Rutas absolutas obligatorias para `agentes.cc.ejecutable` y `herramientas.git`.
  - `proyecto.json` validado: el nombre coincide con la carpeta, los límites solo bajan y las denegaciones no se quitan.
  - `orq proyecto nuevo`, con sugerencias de rutas sin usar el `PATH`.
  - Candado de instancia.

  Verificar con las pruebas de las specs `proyectos` y `estado-cowork` ("Carpeta de Cowork…"), y con "Nombre suelto" y "PATH engañoso" de `adaptadores-agente`.
  - Pruebas: `pruebas/test_config.py` (30) y `pruebas/test_candado.py` (5):
    - `PruebaRaizDeEstado`: raíz por defecto, `ORQ_RAIZ` y `--raiz`, raíz dentro de un repo o de un worktree.
    - `PruebaCarpetaCowork`: por defecto; dentro de la raíz, la raíz dentro de ella y dentro de un repo.
    - `PruebaEjecutables`: `test_nombre_suelto_no_disponible`, `test_path_enganoso_no_se_consulta`, ruta inexistente y git obligatorio.
    - `PruebaProyectos`: válido, nombre que no coincide, repo inexistente, límites que solo bajan, `test_intento_de_permitir_git_push` y estado separado.
    - `PruebaProyectoNuevo`: carpetas de Cowork exactas, no pisa un proyecto existente, sugerencias sin `PATH` y CLI.
    - `PruebaCandado`: segunda instancia sin escribir, candado abandonado registrado y `proceso_vivo`.

## 2. Registro de tareas y entrada

- [x] 2.1 [M] Implementar `registro.py`:
  - Modelo de tarea y valores por defecto.
  - Escritura atómica con `.bak`, reintentos ante `PermissionError`, recuperación desde `.bak` y detección de escrituras externas.

  Verificar con las pruebas de "Registro JSON por proyecto con un solo escritor" y "Campos mínimos".
  - Pruebas: `pruebas/test_registro.py` (17):
    - `PruebaCamposMinimos`: lo mínimo, gate por defecto, agente no permitido, formatos, campos reservados y desconocidos, red.
    - `PruebaEscrituraAtomica`: `.bak`, temporal primero, registro corrupto y copia, reintentos ante `PermissionError`, `test_lector_real_con_el_archivo_abierto` (Windows) y escritura externa.
- [x] 2.2 [M] Implementar la máquina de estados con actores (orquestador, cowork, sebastian), historial y estados terminales, más `orq tarea reintentar|cancelar` vía `decisiones\`. Los archivos que pidan decidir un gate se rechazan. Verificar con una prueba que recorre todas las transiciones válidas e inválidas y con "Decisión de gate por archivo".
  - Pruebas: `pruebas/test_estados.py` (14) y `pruebas/test_decisiones.py` (9):
    - `test_todas_las_combinaciones`: 7 estados × 7 estados × 3 actores × 5 vías contra una tabla escrita aparte.
    - Gates solo por el tablero.
    - `test_decision_de_gate_por_archivo_se_rechaza`: 4 variantes, cada una con un evento de seguridad.
    - `orq tarea` por CLI.
- [x] 2.3 [M] Implementar `entrada.py`:
  - Operaciones `crear` en lote (todo o nada), `editar`, `cancelar` y `reintentar`.
  - Validación de ids, ciclos y campos prohibidos.
  - Los `.tmp` se ignoran; un JSON ilegible se reintenta durante 60 s.
  - Acuses en `respuestas\`, con `procesadas\` y `rechazadas\`.
  - Conversión de trabajos v0 de `tipo: cc`, y rechazo de `tipo: git` o con `repo`.

  Verificar con las pruebas de la entrada en `registro-tareas` y de "Trabajos v0 en la entrada del v1".
  - Pruebas: `pruebas/test_entrada.py` (27):
    - Lote con dependencias, todo o nada (dependencia inexistente, ciclo, id repetido, un agente inválido) y ruta libre rechazada.
    - Editar, cancelar y reintentar; Cowork no aprueba gates.
    - `test_solicitud_invalida_no_toca_lo_que_hay_en_memoria`.
    - `.tmp` ignorado y JSON ilegible por 60 s.
    - Trabajos v0: `cc` convertido, `git` y `repo` rechazados.

## 3. Eventos

- [x] 3.1 [M] Implementar `eventos.py` y `redaccion.py`:
  - Esquema común con lista blanca por tipo.
  - Lector que ignora la última línea incompleta.
  - Redacción de secretos, truncado a 4 KB y `texto_mensajes: "nunca"`.

  Verificar con una prueba por patrón de secreto y otra con un mensaje de 50.000 caracteres.
  - Pruebas: `pruebas/test_redaccion.py` (15, una por patrón más el extra del proyecto y el texto sin secretos) y `pruebas/test_eventos.py` (20):
    - Append-only y línea incompleta.
    - Campos por tipo, incluido `gate`.
    - Evento desconocido contado en `fin`.
    - Sin contenido de archivos de datos y secretos en un comando.
    - `test_mensaje_de_50000_caracteres` y caracteres de varios bytes.
    - Rutas relativas al worktree o con `~`.
- [x] 3.2 [S] Implementar el tope de 2.000 eventos de detalle por intento (con `eventos_omitidos`) y la rotación por tamaño. Verificar con pruebas que usan topes pequeños por configuración.
  - Pruebas: `pruebas/test_eventos_topes.py` (10):
    - `test_agente_muy_conversador` (3.000 → 2.000 y `eventos_omitidos: 1000`).
    - `archivo`, `error` y `fin` siempre se escriben, y el tope es por intento.
    - `test_supera_el_tope`, `test_ya_hay_cinco_rotados`, rotación entre líneas y `seq` que continúa.
    - Topes desde `config.json` y `texto_mensajes` del proyecto.

## 4. Adaptador cc, ejecución y seguridad

- [x] 4.1 [M] Crear `pruebas/falsos/agente_falso.py --como cc`:
  - Guiones `ok`, `lectura`, `limite`, `error`, `colgado`, `hijo_largo`, `sesion_inexistente` e `intenta_commit`, con el formato `stream-json` documentado y sus fuentes citadas al inicio de cada fixture.
  - Una traza con argv, stdin, carpeta y nombres de variables.

  Verificar que cada guion produce una salida que el adaptador lee sin errores.
  - Guiones extra: `negado`, `limite_texto`, `limite_sin_hora` y `sin_final`. Además `pruebas/falsos/orquestador_mini.py` para "El orquestador muere".
  - Pruebas: `pruebas/test_falso.py` (3): cada guion se lee sin errores ni líneas no JSON, traza sin valores de variables y `--version`.
- [x] 4.2 [M] Implementar `adaptadores/base.py` y `corrida.py`:
  - `Popen` con ruta absoluta y `CREATE_NO_WINDOW`; lectura por líneas; final de stderr redactado.
  - Job Object propio y por tarea, con `taskkill` de respaldo.
  - Tiempo máximo y cancelación.

  Verificar con los guiones `colgado` y `hijo_largo`, con la prueba "El orquestador muere" (orquestador lanzado como subproceso) y con un adaptador de prueba mínimo.
  - Job Objects en `orquestador/procesos.py` (ctypes, sin dependencias).
  - Pruebas: `pruebas/test_corrida.py` (4): adaptador mínimo, `test_se_acaba_el_tiempo`, cancelación con hijo vivo y `PruebaOrquestadorMuere`.
- [x] 4.3 [M] Implementar `adaptadores/cc.py`:
  - Comando y perfil `--settings`, con el respaldo de `restricted: false`.
  - `--session-id` y `--resume` con validación de UUID.
  - Normalización, límite del plan, consumo y versión mínima.

  Verificar con las pruebas de `adaptadores-agente` y "Normalización de Claude Code".
  - Pruebas: `pruebas/test_adaptador_cc.py` (19): comando, herramientas, perfil, `regla_ruta`, retomar, respaldo sin `--restricted`, entorno, normalización (`ok`, `lectura`, `negado`, consumo, `sin_final`), límite con hora, por texto y al día siguiente, y versión.
- [x] 4.4 [M] Implementar las revisiones previas al lanzamiento en `seguridad.py`:
  - Banderas prohibidas.
  - Entorno filtrado (sin secretos ni `ANTHROPIC_API_KEY`).
  - Worktree sin secretos.
  - Skills versionadas con `allowed-tools` o `hooks` contra las huellas aprobadas.
  - Prompt solo por stdin e ids validados.

  Verificar con las pruebas de esos requisitos de `seguridad-agentes` (incluidos "Adaptador defectuoso" y "Prompt con comandos").
  - Pruebas: `pruebas/test_seguridad.py` (18, con combinaciones en `subTest`):
    - Banderas y valores prohibidos en todas sus formas.
    - Prompt en argv o fuera de stdin.
    - Entorno filtrado y variables permitidas por proyecto.
    - Worktree con `.env` o skills peligrosas sin huella.
    - En el bucle: `test_adaptador_defectuoso_no_lanza`, `test_entorno_del_agente_sin_secretos`, `facturar_por_api`, `.env` en el worktree, prompt con comandos e `test_id_de_sesion_malicioso`.
- [x] 4.5 [M] Implementar la auditoría de git antes y después de cada corrida (HEAD, refs, reflog, stash, worktrees y huellas de `.git/config` y `.git/hooks`, con `GIT_OPTIONAL_LOCKS=0`) y la matriz de garantías de cc en el evento `inicio`. Verificar que el guion `intenta_commit` deja la tarea `fallida` con clase `violacion`, que una corrida limpia no reporta nada, y con "Claude Code en Windows nativo".
  - Pruebas: `pruebas/test_auditoria.py`:
    - `test_el_agente_hizo_un_commit` (`violacion` que nombra `refs/heads/login`) y corrida limpia.
    - `test_matriz` en `inicio` y matriz de Windows.
    - `PruebaFotoDeGit`: commit, rama, checkout, stash, config y hook.

## 5. Planificador

- [x] 5.1 [S] Implementar `worktrees.py`: crear o reutilizar con candado por repo y el `git` de la config, sin borrar nunca. Verificar con "Worktree nuevo" y "Dos cambios nuevos a la vez".
  - Pruebas: `pruebas/test_worktrees.py` (6): nuevo, reutiliza, rama existente, `test_dos_cambios_nuevos_a_la_vez` (los `git worktree add` van de a uno), carpeta que no es worktree y no borra nada.
- [x] 5.2 [M] Implementar el bucle de `planificador.py`:
  - Candidatas y prioridad.
  - Límites global y por agente sumando proyectos.
  - Dependencias y bloqueos (incluida la dependencia fallida).
  - Un cambio a la vez, incluso con una tarea en `esperando_gate`.

  Verificar con el guion `colgado` que nunca se pasan los límites y que una tarea con dependencias abiertas no lanza proceso (la traza del falso queda vacía).
  - Pruebas: `pruebas/test_planificador.py` (13):
    - Límites por agente, global y del proyecto; cambios distintos en paralelo.
    - Dependencia abierta (sin lanzamiento en la traza), desbloqueo y dependencia fallida.
    - Mismo cambio en curso y en `esperando_gate`; prioridad; agente con versión antigua.
    - `PruebaEventosDeSeguridad`: gate por archivo en `decisiones\` y Cowork pidiendo aprobar quedan como evento `error` clase `seguridad` (pendiente de la parte 1).
- [x] 5.3 [M] Implementar:
  - Las sesiones por `(cambio, agente)`, guardadas antes de lanzar.
  - El límite del plan (`agotado_hasta`, `no_antes_de`, `fallida` al séptimo).
  - El `diffstat` con archivos nuevos y la huella del estado al pasar a `esperando_gate`.

  Verificar con los guiones `limite` y `sesion_inexistente` y con "Archivo nuevo" del tablero.
  - Pruebas: `pruebas/test_sesiones_limite.py` (9):
    - Sesiones: se guarda antes de lanzar y se retoma, `nueva_sesion` y `test_sesion_que_ya_no_existe`.
    - Plan agotado (otra tarea de cc no se lanza), límite sin hora (30 min) y `test_septimo_limite_deja_la_tarea_fallida`.
    - `diffstat` con `app.py` nuevo y huella que cambia al tocar un archivo o agregar uno nuevo.
- [x] 5.4 [M] Implementar la recuperación al reiniciar: `en_curso` pasa a `pendiente` con `interrupciones`, más de 2 deja la tarea `fallida`, y se verifica que no quede vivo el proceso anterior. Verificar matando el orquestador a mitad de una corrida y reiniciándolo: el estado, el historial y la huella sobreviven y el siguiente intento retoma la sesión.
  - Pruebas: `pruebas/test_reinicio.py` (6):
    - `test_reinicio_con_una_tarea_en_curso`: `orq.py correr` como subproceso, muerto de golpe; el agente muere con él y el siguiente intento usa `--resume` con la misma sesión.
    - `test_tercera_interrupcion`, proceso anterior vivo que se termina y pid reutilizado que no se toca.
    - Estado intacto tras reiniciar y cancelación pedida antes del corte.
  - Pendientes de la parte 1:
    - Candado con hora de creación: `test_candado.test_pid_reutilizado_se_trata_como_abandonado`.
    - Rotación postergada en `registro.log`: `test_eventos_topes.test_rotacion_postergada_queda_en_registro_log`.

## 6. Tablero y gate por botón

- [x] 6.1 [M] Implementar el servidor del tablero como hilo de `orq correr` (`--sin-tablero` para omitirlo):
  - Solo en `127.0.0.1`; error si el puerto está ocupado.
  - Enlace de entrada de un solo uso impreso en la terminal y cookie de sesión en memoria.
  - `Host`, `Origin`, CSP y `X-Frame-Options`.

  Verificar con las pruebas de "Solo en 127.0.0.1", "Acceso con enlace de un solo uso…" (incluida "Nada en disco") y "Defensas del navegador".
  - `orquestador/tablero.py` (`ThreadingHTTPServer` con `SO_EXCLUSIVEADDRUSE`, sin registro de peticiones) y estáticos en `orquestador/estaticos/` sin scripts en línea.
  - Pruebas en `pruebas/test_tablero.py`:
    - `test_direccion_de_escucha` y `test_puerto_ocupado`.
    - `test_con_y_sin_tablero` y `test_puerto_ocupado_termina_con_error` (`orq correr` como subproceso).
    - `test_sin_sesion`, `test_canje_del_enlace`, `test_nada_en_disco` y `test_reinicio`.
    - `test_rebinding_de_dns`, `test_peticion_desde_otra_pagina`, `test_cabeceras` y `test_paginas_sin_scripts_en_linea`.
  - "Conexión desde otra interfaz" queda en la verificación manual: las pruebas solo pueden usar 127.0.0.1.
- [x] 6.2 [M] Implementar la API y las páginas:
  - Kanban con filtros.
  - Detalle en vivo por polling desde `seq`, con resultado, consumo, `diffstat` y niveles.
  - Vista de consumo.

  Agregar la prueba de solo lectura (todas las rutas y métodos que no son de gate dejan iguales los archivos de la raíz y de la carpeta de Cowork). Verificar también que un evento nuevo aparece en 3 s o menos.
  - El tablero lee una instantánea que publica el bucle al final de cada ciclo (`vistas.py`) y los eventos con `LectorEventos` (solo lectura, sigue la rotación).
  - Pruebas en `pruebas/test_tablero.py`:
    - `test_bateria_de_peticiones`: 16 rutas × 6 métodos, con y sin sesión.
    - `test_filtro_por_proyecto_y_agente` y `test_agente_agotado`.
    - `test_actividad_en_vivo`: el evento llega en menos de 3 s.
    - `test_tarea_esperando_gate`, `test_diff_durante_la_ejecucion` y `test_sin_diff_calculado`.
    - `test_vista_de_consumo`: costo estimado y "sin costo informado".
- [x] 6.3 [M] Implementar `gates.py` y las rutas `preparar` y `confirmar`:
  - CSRF, origen y huella en ambos pasos.
  - Código de 6 dígitos solo en la terminal, de un solo uso y por 120 s; bloqueo tras 3 errores.
  - Cola en memoria hacia el bucle y registro en historial, evento y terminal.
  - Aviso de integridad del código con `--permitir-codigo-modificado`.

  Verificar con todas las pruebas de `aprobacion-gates`, incluida la que revisa que el código no aparece en HTTP ni en disco.
  - `orquestador/gates.py` e `orquestador/integridad.py`. El bucle atiende la cola, recalcula la huella con git y aplica la decisión.
  - Pruebas en `pruebas/test_gates.py`, por HTTP contra el tablero real:
    - `test_aprobacion_con_codigo_de_la_terminal`: aplicada por el bucle, rastro completo, código usado y código ausente en HTTP y en disco.
    - `test_rechazo_exige_nota_y_vuelve_a_pendiente`.
    - `test_worktree_cambio_despues_de_revisar`: huella cambiada y archivo nuevo.
    - `test_vencido_y_usado` y `test_bloqueo_hasta_reiniciar`.
    - `test_codigo_modificado_con_permiso` y `test_codigo_modificado_deshabilita_los_gates`.
    - `test_origen_ajeno`, `test_sin_token_csrf`, `test_sin_sesion`, `test_sin_origin_o_sin_json` y `test_tarea_que_no_espera_gate`.
    - `test_revisa_el_codigo_de_la_instalacion`.

## 7. Lectura del estado por Cowork

- [x] 7.1 [M] Implementar `salida_cowork.py`: `estado.json`, `eventos-recientes.json`, `consumo.json`, `resultados\` y `diffstat\`, con escritura atómica como máximo 2 s después de cada cambio, sin leer nunca la salida. Verificar con las pruebas de `estado-cowork`, incluida "Secretos sembrados" (entorno, prompt, stderr y comando).
  - Pruebas en `pruebas/test_salida_cowork.py`:
    - `test_cowork_lee_el_avance` y `test_eventos_recientes_acotados` (5.000 → 300, textos ≤ 500).
    - `test_secretos_sembrados`: cinco secretos, dos sin formato conocido, que solo protege la lista blanca.
    - `test_archivo_de_datos_leido_por_el_agente` y `test_cowork_edita_la_salida`.

## 8. Compatibilidad v0

- [x] 8.1 [S] Agregar pruebas de regresión de `puente.py` con el falso de cc (guiones `ok` y `limite`) sin modificar `puente.py`. Verificar que pasan y que `git diff --stat -- puente.py` queda vacío.
  - Pruebas en `pruebas/test_puente_v0.py`: una copia byte a byte de `puente.py` corre en una carpeta temporal con un `claude.cmd` que lanza el falso.
    - `test_trabajo_v0_con_claude_code_falso` y `test_limite_de_plan_en_v0`.
    - `test_puente_intacto`: mismo SHA-256 y `git diff --stat HEAD -- puente.py` vacío.
- [x] 8.2 [M] Implementar `orq importar-v0`: simula por defecto, aplica con `--aplicar` y deja el origen intacto. Verificar sobre una carpeta v0 sintética (comparando huellas y fechas del origen) y con "Sesión importada se retoma".
  - `orquestador/importar_v0.py`: toma el candado, guarda las sesiones `(cambio, cc)` y deja los trabajos en la entrada de Cowork (no escribe `tareas.json`).
  - Pruebas en `pruebas/test_importar_v0.py`:
    - `test_simulacion`.
    - `test_importacion_aplicada_y_sesion_retomada`: `--resume` con la sesión del v0; además cubre "Trabajo v0 corre en el v1".
    - `test_no_aplica_con_orq_correr_andando`.

## 9. Documentación e integración

- [x] 9.1 [S] Documentar y completar los comandos:
  - Sección v1 (E1) en `LEEME.md`: instalación, rutas absolutas, conectar en Cowork solo `Orquestador-Cowork\<p>` y cómo aprobar un gate con el código de la terminal.
  - `config.example.json` y `proyecto.example.json` con valores seguros.
  - `docs/verificacion-manual.md` para cc: `--restricted` con OAuth, versión, `claude auth status` y el gate en el navegador.
  - `orq estado`.

  Verificar que los ejemplos cargan, que cada comando documentado responde a `--help` y que `orq estado` imprime el resumen con el falso.
  - Los ejemplos del v1 quedan en `ejemplos/`: `config.example.json` de la raíz sigue siendo el del puente v0.
  - Pruebas:
    - `pruebas/test_documentacion.py`: `test_config_de_ejemplo`, `test_proyecto_de_ejemplo`, `test_leeme_documenta_comandos_y_cowork`, `test_verificacion_manual` y `test_resumen_con_el_falso`.
    - `pruebas/test_base.py`: `test_cada_subcomando_responde_a_help`.
- [x] 9.2 [M] Agregar una prueba de extremo a extremo con el falso de cc: lote de Cowork con dependencias, límite de plan, reinicio a mitad, gate aprobado por el flujo completo del tablero, salida de Cowork actualizada y tablero leyendo todo. Escribir `pruebas/COBERTURA.md` (escenario de spec → prueba) y correr `openspec validate orquestador-v1 --strict`. Verificar que todo pasa con la red bloqueada.
  - Pruebas: `pruebas/test_extremo.py` (`test_flujo_completo`) y `pruebas/COBERTURA.md`.
  - Esta prueba destapó un falso positivo de la auditoría (4.5) con dos cambios del mismo repo en paralelo. Se corrigió con `worktrees.creados_entre`: se ignoran solo los worktrees y ramas que el orquestador estuvo creando durante esa corrida, y solo sus altas y cambios, nunca sus bajas.
  - Pruebas del arreglo: `test_auditoria.test_worktree_que_crea_el_orquestador_en_paralelo`, `test_worktree_a_medio_crear`, `test_solo_cuentan_las_creaciones_durante_la_corrida` y `test_dos_cambios_a_la_vez_terminan_bien`.

## Workflow follow-up

- Sebastian borra `openspec/changes/orquestador-v1/specs/paridad-capacidades/`, que es de E3 y cuyo contenido está en `docs/referencia/requisitos-e2-e4.md`, y vuelve a correr `openspec validate orquestador-v1 --strict`.
- Gate de Sebastian sobre este change antes del apply; incluye las decisiones 7 y 19 a 23.
- Verificación manual de cc y del gate en el navegador.
- Commit (lo hace Sebastian) y archive.
- Abrir E2 según `docs/etapas.md`.
