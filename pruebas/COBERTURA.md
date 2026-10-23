# Cobertura: escenario de spec → prueba

Specs de `openspec/changes/orquestador-v1/specs/`. Formato de la prueba: `archivo.método` (sin `test_` en el
archivo cuando se repite). "Manual" remite a `docs/verificacion-manual.md`.

## proyectos

| Escenario | Prueba |
|---|---|
| Raíz por defecto | `test_config.test_raiz_por_defecto_en_userprofile_y_crea_proyectos` |
| Raíz dentro de un repo | `test_config.test_raiz_dentro_de_un_repo_registrado`, `test_raiz_dentro_de_un_worktree` |
| Proyecto válido | `test_config.test_proyecto_valido`, `test_documentacion.test_proyecto_de_ejemplo` |
| Nombre que no coincide | `test_config.test_nombre_que_no_coincide_se_ignora` |
| Repo inexistente | `test_config.test_repo_inexistente_no_afecta_a_los_demas` |
| Estado separado | `test_config.test_estado_separado_por_proyecto`, `test_registro.test_estado_separado_por_proyecto` |
| Ruta libre en una tarea | `test_entrada.test_ruta_libre_en_una_tarea` |
| Límite mayor que el global | `test_config.test_limite_mayor_que_el_global` |
| Intento de quitar una denegación obligatoria | `test_config.test_intento_de_permitir_git_push` |
| Segunda instancia | `test_candado.test_segunda_instancia_termina_sin_escribir`, `test_importar_v0.test_no_aplica_con_orq_correr_andando` |
| Candado abandonado | `test_candado.test_candado_abandonado_se_toma_y_se_registra`, `test_pid_reutilizado_se_trata_como_abandonado` |

## registro-tareas

| Escenario | Prueba |
|---|---|
| Escritura atómica | `test_registro.test_escritura_atomica_con_bak`, `test_se_escribe_primero_el_temporal` |
| Registro corrupto al iniciar | `test_registro.test_registro_corrupto_usa_la_copia`, `test_registro_y_copia_corruptos` |
| Reemplazo con el archivo abierto por un lector | `test_registro.test_reemplazo_con_reintentos`, `test_lector_real_con_el_archivo_abierto` |
| Escritura externa detectada | `test_registro.test_escritura_externa_detectada` |
| Tarea creada con lo mínimo | `test_registro.test_tarea_creada_con_lo_minimo` |
| Agente no permitido | `test_registro.test_agente_no_permitido` |
| Historial de una transición | `test_estados.test_entrada_de_historial` |
| Tarea terminal | `test_estados.test_terminales_sin_salida` |
| Termina bien sin gate | `test_sesiones_limite.test_se_guarda_antes_de_lanzar_y_se_retoma`, `test_auditoria.test_corrida_limpia` |
| Termina bien con gate | `test_sesiones_limite.test_huella_al_esperar_gate` |
| Error con intentos disponibles | `test_planificador.test_error_con_y_sin_intentos_disponibles` |
| Error sin intentos disponibles | `test_planificador.test_error_con_y_sin_intentos_disponibles` |
| Aprobar un gate | `test_gates.test_aprobacion_con_codigo_de_la_terminal`, `test_estados.test_aprobar_y_rechazar_por_tablero` |
| Rechazar con nota | `test_gates.test_rechazo_exige_nota_y_vuelve_a_pendiente`, `test_estados.test_rechazo_sin_nota` |
| Decisión de gate por archivo | `test_decisiones.test_decision_de_gate_por_archivo_se_rechaza`, `test_planificador.test_gate_por_archivo_en_decisiones` |
| Reintento de una tarea fallida | `test_decisiones.test_reintento_de_tarea_fallida` |
| Cancelar una tarea que espera gate | `test_decisiones.test_cancelar_tarea_que_espera_gate` |
| Cowork intenta aprobar un gate | `test_entrada.test_cowork_intenta_aprobar_un_gate`, `test_planificador.test_cowork_pide_aprobar` |
| Cowork edita una tarea en curso | `test_entrada.test_editar_en_curso_se_rechaza` |
| Cowork cancela una tarea en curso | `test_entrada.test_cancelar_en_curso`, `test_reinicio.test_cancelacion_pedida_antes_del_corte` |
| Lote de tareas con dependencias | `test_entrada.test_lote_con_dependencias`, `test_extremo.test_flujo_completo` |
| Solicitud inválida | `test_entrada.test_todo_o_nada`, `test_solicitud_invalida_no_toca_lo_que_hay_en_memoria` |
| Id repetido | `test_entrada.test_id_repetido_con_el_registro`, `test_registro.test_id_repetido_en_el_registro` |
| Archivo temporal | `test_entrada.test_archivo_temporal_se_ignora` |
| JSON incompleto que se completa | `test_entrada.test_json_incompleto_que_se_completa` |

## adaptadores-agente

| Escenario | Prueba |
|---|---|
| Ciclo común | `test_corrida.test_adaptador_minimo_con_el_mismo_ciclo` |
| Adaptador de prueba | `test_corrida.test_adaptador_minimo_con_el_mismo_ciclo` |
| Ruta absoluta válida | `test_config.test_ruta_absoluta_valida`, `test_lista_con_ruta_absoluta` |
| Nombre suelto | `test_config.test_nombre_suelto_no_disponible` |
| PATH engañoso | `test_config.test_path_enganoso_no_se_consulta` |
| Ejecutable falso para pruebas | `test_falso.test_cada_guion_se_lee_sin_errores` (todas las pruebas del bucle lanzan `python.exe` por ruta absoluta) |
| Versión antigua | `test_adaptador_cc.test_version_antigua`, `test_planificador.test_version_antigua_deja_la_tarea_esperando` |
| Versión más nueva | `test_adaptador_cc.test_version_mas_nueva` |
| Comando de cc | `test_adaptador_cc.test_comando_de_cc`; con el binario real: manual §2 y §3 |
| Respaldo sin restricted | `test_adaptador_cc.test_respaldo_sin_restricted` |
| Retomar | `test_adaptador_cc.test_retomar`, `test_sesiones_limite.test_se_guarda_antes_de_lanzar_y_se_retoma` |
| Sesión que ya no existe | `test_sesiones_limite.test_sesion_que_ya_no_existe` |
| Límite con hora | `test_adaptador_cc.test_limite_con_hora`, `test_hora_pasada_es_de_manana` |
| Límite solo por texto | `test_adaptador_cc.test_limite_solo_por_texto` |
| Consumo de Claude Code | `test_adaptador_cc.test_consumo` |
| Agente termina sin evento final | `test_adaptador_cc.test_termina_sin_evento_final` |
| Guion de límite de uso | `test_sesiones_limite.test_plan_agotado`, `test_puente_v0.test_limite_de_plan_en_v0` |
| Sin red | `test_base.PruebaRedBloqueada`, `test_extremo.test_flujo_completo` |

## seguridad-agentes

| Escenario | Prueba |
|---|---|
| Comandos de cc | `test_seguridad.test_comandos_de_cc_en_todas_las_combinaciones` |
| Adaptador defectuoso | `test_seguridad.test_adaptador_defectuoso_no_lanza`, `test_revision_rechaza_cada_forma_prohibida` |
| Repo con settings propios | `test_adaptador_cc.test_comando_de_cc` (`--restricted` o `--setting-sources user`, `--settings` y `--strict-mcp-config`) |
| Perfil generado de cc | `test_adaptador_cc.test_perfil` |
| Red apagada por defecto | `test_adaptador_cc.test_herramientas_sin_y_con_red`, `test_registro.test_red_sin_permiso_del_proyecto` |
| Claude Code en Windows nativo | `test_auditoria.test_matriz_de_cc_en_windows`, `test_matriz_en_el_evento_inicio` |
| Alguien copió un .env al worktree | `test_seguridad.test_env_copiado_al_worktree`, `test_archivos_con_secretos` |
| Skill con allowed-tools sin aprobar | `test_seguridad.test_skill_que_concede_permisos` |
| Skill aprobada | `test_seguridad.test_skill_con_hooks_y_skill_inofensiva` |
| Variable con secreto | `test_seguridad.test_variables_con_secreto`, `test_entorno_del_agente_sin_secretos` |
| Suscripción en vez de API | `test_seguridad.test_facturar_por_api` |
| El agente hizo un commit | `test_auditoria.test_el_agente_hizo_un_commit`, `test_cada_cambio_se_nombra` |
| Corrida limpia | `test_auditoria.test_corrida_limpia`, `test_dos_cambios_a_la_vez_terminan_bien` |
| Prompt con comandos | `test_seguridad.test_prompt_con_comandos`, `test_prompt_en_los_argumentos` |
| Id de sesión malicioso | `test_seguridad.test_id_de_sesion_malicioso` |

## eventos-actividad

| Escenario | Prueba |
|---|---|
| Evento agregado | `test_eventos.test_evento_agregado_es_una_linea_al_final` |
| Línea a medio escribir | `test_eventos.test_lector_ignora_la_linea_incompleta` |
| Campos por tipo | `test_eventos.test_campos_por_tipo` |
| Evento del propio orquestador | `test_eventos.test_evento_del_orquestador_sin_agente` |
| Evento desconocido del agente | `test_eventos.test_evento_desconocido_del_agente_se_cuenta` |
| Corrida típica | `test_adaptador_cc.test_corrida_tipica` |
| Negación de permiso | `test_adaptador_cc.test_negacion_de_permiso` |
| Lectura de un archivo de datos | `test_eventos.test_lectura_de_archivo_de_datos`, `test_adaptador_cc.test_lectura_sin_contenido` |
| Secreto en un comando | `test_eventos.test_secreto_en_un_comando` |
| Proyecto sin texto de mensajes | `test_eventos.test_proyecto_sin_texto_de_mensajes` |
| Mensaje largo | `test_eventos.test_mensaje_de_50000_caracteres` |
| Agente muy conversador | `test_eventos_topes.test_agente_muy_conversador` |
| Supera el tope | `test_eventos_topes.test_supera_el_tope`, `test_rotacion_postergada_queda_en_registro_log` |
| Ya hay cinco rotados | `test_eventos_topes.test_ya_hay_cinco_rotados` |

## planificacion-ejecucion

| Escenario | Prueba |
|---|---|
| Límite por agente | `test_planificador.test_limite_por_agente`, `test_limite_del_proyecto` |
| Límite global | `test_planificador.test_limite_global` |
| Cupo libre | `test_planificador.test_cupo_libre_y_cambios_distintos_en_paralelo` |
| Dependencia pendiente | `test_planificador.test_dependencia_abierta_no_lanza` |
| Dependencia esperando gate | `test_extremo.test_flujo_completo` (T-2 queda `bloqueada` mientras T-1 espera gate) |
| Dependencias cumplidas | `test_planificador.test_se_desbloquea_al_quedar_hecha` |
| Dependencia fallida | `test_planificador.test_dependencia_fallida` |
| Mismo cambio en curso | `test_planificador.test_mismo_cambio` |
| Mismo cambio esperando gate | `test_planificador.test_mismo_cambio_esperando_gate` |
| Cambios distintos en el mismo repo | `test_planificador.test_cupo_libre_y_cambios_distintos_en_paralelo`, `test_auditoria.test_dos_cambios_a_la_vez_terminan_bien` |
| Worktree nuevo | `test_worktrees.test_worktree_nuevo` |
| Dos cambios nuevos a la vez | `test_worktrees.test_dos_cambios_nuevos_a_la_vez` |
| Retoma la sesión | `test_sesiones_limite.test_se_guarda_antes_de_lanzar_y_se_retoma` |
| Sesión nueva pedida | `test_sesiones_limite.test_nueva_sesion_pedida` |
| Plan agotado | `test_sesiones_limite.test_plan_agotado` |
| Límite sin hora de reinicio | `test_sesiones_limite.test_limite_sin_hora_espera_media_hora` |
| Demasiados límites seguidos | `test_sesiones_limite.test_septimo_limite_deja_la_tarea_fallida` |
| Se acaba el tiempo | `test_corrida.test_se_acaba_el_tiempo` |
| Cancelación con hijos | `test_corrida.test_cancelacion_con_hijos` |
| El orquestador muere | `test_corrida.test_el_orquestador_muere_y_mueren_sus_agentes` |
| Reinicio con una tarea en curso | `test_reinicio.test_reinicio_con_una_tarea_en_curso`, `test_extremo.test_flujo_completo` |
| Tercera interrupción | `test_reinicio.test_tercera_interrupcion` |
| Estado intacto tras reinicio | `test_reinicio.test_estado_intacto_tras_reinicio` |

## tablero

| Escenario | Prueba |
|---|---|
| Arranque con tablero | `test_tablero.test_con_y_sin_tablero` (subproceso `orq correr`) |
| Sin tablero | `test_tablero.test_con_y_sin_tablero` |
| Dirección de escucha | `test_tablero.test_direccion_de_escucha`, `test_puerto_ocupado`, `test_puerto_ocupado_termina_con_error` |
| Conexión desde otra interfaz | Manual §4 (las pruebas solo pueden usar 127.0.0.1); el bind a 127.0.0.1 lo cubre `test_direccion_de_escucha` |
| Sin sesión | `test_tablero.test_sin_sesion` |
| Canje del enlace | `test_tablero.test_canje_del_enlace` |
| Nada en disco | `test_tablero.test_nada_en_disco` |
| Reinicio | `test_tablero.test_reinicio` |
| Rebinding de DNS | `test_tablero.test_rebinding_de_dns` |
| Petición desde otra página | `test_tablero.test_peticion_desde_otra_pagina`, `test_cabeceras`, `test_paginas_sin_scripts_en_linea` |
| Batería de peticiones | `test_tablero.test_bateria_de_peticiones` |
| Método de escritura | `test_tablero.test_bateria_de_peticiones` |
| Filtro por proyecto | `test_tablero.test_filtro_por_proyecto_y_agente` |
| Agente agotado | `test_tablero.test_agente_agotado`, `test_extremo.test_flujo_completo` |
| Actividad en vivo | `test_tablero.test_actividad_en_vivo` |
| Tarea esperando gate | `test_tablero.test_tarea_esperando_gate`; con navegador: manual §4 |
| Diff durante la ejecución | `test_tablero.test_diff_durante_la_ejecucion` |
| Archivo nuevo | `test_sesiones_limite.test_diff_stat_con_archivo_nuevo` |
| Sin diff calculado | `test_tablero.test_sin_diff_calculado` |
| Costo estimado | `test_tablero.test_vista_de_consumo` |
| Dato que el agente no informa | `test_tablero.test_vista_de_consumo` |

## aprobacion-gates

| Escenario | Prueba |
|---|---|
| Aprobación aplicada por el bucle | `test_gates.test_aprobacion_con_codigo_de_la_terminal` |
| Gate de una tarea que no espera gate | `test_gates.test_tarea_que_no_espera_gate` |
| Código correcto | `test_gates.test_aprobacion_con_codigo_de_la_terminal` |
| Código vencido o usado | `test_gates.test_vencido_y_usado`, `test_aprobacion_con_codigo_de_la_terminal` (reuso) |
| El código no sale de la terminal | `test_gates.test_aprobacion_con_codigo_de_la_terminal` |
| El worktree cambió después de revisar | `test_gates.test_worktree_cambio_despues_de_revisar` |
| Archivo nuevo sin seguimiento | `test_gates.test_worktree_cambio_despues_de_revisar`, `test_sesiones_limite.test_huella_al_esperar_gate` |
| Sin token CSRF | `test_gates.test_sin_token_csrf` |
| Origen ajeno | `test_gates.test_origen_ajeno`, `test_sin_origin_o_sin_json` |
| Sin sesión | `test_gates.test_sin_sesion` |
| Tres códigos malos | `test_gates.test_bloqueo_hasta_reiniciar` |
| Rastro de una aprobación | `test_gates.test_aprobacion_con_codigo_de_la_terminal` |
| Código modificado | `test_gates.test_codigo_modificado_deshabilita_los_gates`, `test_revisa_el_codigo_de_la_instalacion` |
| Modo desarrollo explícito | `test_gates.test_codigo_modificado_con_permiso` |

## estado-cowork

| Escenario | Prueba |
|---|---|
| Carpetas por defecto | `test_config.test_cowork_por_defecto`, `test_crea_proyecto_y_carpetas_de_cowork` |
| Carpeta de Cowork dentro de la raíz de estado | `test_config.test_cowork_dentro_de_la_raiz_es_error_sin_escribir` |
| Cowork lee el avance | `test_salida_cowork.test_cowork_lee_el_avance` |
| Eventos recientes acotados | `test_salida_cowork.test_eventos_recientes_acotados` |
| Secretos sembrados | `test_salida_cowork.test_secretos_sembrados` |
| Archivo de datos leído por el agente | `test_salida_cowork.test_archivo_de_datos_leido_por_el_agente` |
| Cowork edita la salida | `test_salida_cowork.test_cowork_edita_la_salida` |

## compatibilidad-v0

| Escenario | Prueba |
|---|---|
| Trabajo v0 con Claude Code falso | `test_puente_v0.test_trabajo_v0_con_claude_code_falso`, `test_puente_intacto` |
| Límite de plan en v0 | `test_puente_v0.test_limite_de_plan_en_v0` |
| Trabajo v0 convertido | `test_entrada.test_trabajo_v0_convertido` |
| Trabajo v0 corre en el v1 | `test_importar_v0.test_importacion_aplicada_y_sesion_retomada` |
| Trabajo de commit | `test_entrada.test_trabajo_v0_de_git_se_rechaza`, `test_trabajo_v0_con_repo_se_rechaza` |
| Simulación | `test_importar_v0.test_simulacion` |
| Importación aplicada | `test_importar_v0.test_importacion_aplicada_y_sesion_retomada` |
| Sesión importada se retoma | `test_importar_v0.test_importacion_aplicada_y_sesion_retomada` |

## Solo verificación manual

- `--restricted` con OAuth, `--permission-prompts none` y la versión con `claude auth status`: manual §1 a §3.
- Gate por botón en un navegador real y conexión desde otra interfaz: manual §4.
- Conectar la carpeta de Cowork en la app: manual §5.

## Operación v1 — parte A

Specs de `openspec/changes/operacion-v1/specs/` (seguridad-agentes y adaptadores-agente). Cada escenario tiene
además una mutación en `out/mutaciones.py` que hace fallar su prueba.

| Escenario | Prueba |
|---|---|
| Cinco capas, variable heredada y respaldo | test_adaptador_cc.PruebaConectoresOperacion.test_capas_con_variable_heredada_y_respaldo |
| Listas de inicio, 60 nombres y omitidos | test_adaptador_cc.PruebaConectoresOperacion.test_inicio_listas_y_omitidas |
| Aviso sin listas | test_adaptador_cc.PruebaConectoresOperacion.test_inicio_sin_listas; test_corrida.PruebaHerramientasOperacion.test_listas_completas_y_herramienta_faltante |
| Lista tolerada fija, sin MCP | test_adaptador_cc.PruebaConectoresOperacion.test_toleradas_vacias_y_sin_mcp |
| Inicio limpio y matriz | test_adaptador_cc.PruebaConectoresOperacion.test_inicio_limpio_guarda_listas_y_matriz |
| Capa ausente, no se lanza | test_seguridad.PruebaCapasOperacion.test_falta_strict_impide_lanzar; test_falta_disallowed_impide_lanzar; test_falta_entorno_impide_lanzar |
| Adaptador que no declara las capas; agente sin capas en el núcleo; variable repetida con otras mayúsculas | test_seguridad.PruebaCapasEnElNucleo |
| Salida que no se puede revisar | test_corrida.PruebaHerramientasOperacion.test_salida_con_forma_inesperada_corta |
| Proyecto que abre MCP | test_seguridad.PruebaCapasOperacion.test_proyecto_mcp_inactivo |
| Conectores, MCP pending, herramienta tardía y sin inicio (con una herramienta pedida); mueren agente e hijo en menos de 15 s | test_corrida.PruebaHerramientasOperacion.test_cortes_matan_proceso |
| Matriz con el control nuevo | test_auditoria.PruebaAuditoriaEnElBucle.test_matriz_de_cc_en_windows |
| Comparación completa, sobrante después del nombre 40 | test_corrida.PruebaHerramientasOperacion.test_listas_completas_y_herramienta_faltante |
| Herramienta pedida ausente | test_corrida.PruebaHerramientasOperacion.test_herramienta_pedida_ausente_termina_ok |
| Fallida sin reintentos | test_planificador.PruebaCorteOperacion.test_conectores_sin_reintento; test_mcp_pendiente_sin_reintento; test_herramienta_tarde_sin_reintento; test_sin_init_sin_reintento |
| Tope de 4096 bytes con nombres largos | test_eventos_topes.PruebaTopeInicioOperacion.test_sesenta_nombres_largos_respetan_tope |
| Paso 7, cinco capas, campos y subpasos | test_documentacion.PruebaConectoresDocumentados.test_paso_siete_cinco_capas_y_campos |

- Las capas con el binario real (cuál basta sola, herramientas propias y escala de `utilization`): manual §7.

## Operación v1 — parte B (tablero)

Specs `tablero` y `registro-tareas` (deltas de operacion-v1).

| Escenario | Prueba |
|---|---|
| Explicación válida e inválida | `test_entrada.PruebaExplicacionYRevisa` |
| Revisión con dependencia automática | `test_entrada.PruebaExplicacionYRevisa` |
| Uso del plan (utilization) | `test_adaptador_cc.PruebaUsoPlan`, `test_planificador.PruebaUsoPlanGuardado` |
| Frases de estación y de error | `test_frases` |
| Vista `tablero()` (turno, agentes, plan, sin prompt) | `test_vistas_tablero` |
| API `/api/tablero` y 401 | `test_tablero.PruebaApiTablero` |
| HTML/CSS sin código en línea; halo de Trabajando con color del agente | `test_tablero.PruebaDefensas.test_estaticos_sin_codigo_en_linea` |
| Nota del código del gate (2 minutos) | `test_tablero.PruebaDefensas.test_estaticos_sin_codigo_en_linea` |
| Rutas del tablero, estáticos sin sesión, página 401 | `test_tablero.PruebaDefensas` |

## Operación v1 — parte C (acceso)

Spec `acceso-tablero`.

| Escenario | Prueba |
|---|---|
| Canje, vencido, anulado, cierre de sesiones | `test_acceso.PruebaEntradas` |
| Aviso sin token; cookie sin Max-Age | `test_acceso.PruebaEntradasEnElTablero` |
| Enlace usado o vencido: página fija (no JSON) | `test_acceso.PruebaEntradasEnElTablero.test_entrar_usado_o_vencido_muestra_pagina_fija` |
| Enter / x en la terminal; sin TTY | `test_acceso.PruebaTerminal` |
| `orq abrir` con candado vivo o abandonado | `test_acceso.PruebaOrqAbrir` |
| `.cmd` con espacios/tildes; rechazo de `%` etc. | `test_acceso.PruebaAccesoDirecto` |
| Ruta relativa absolutizada antes de revisar peligros | `test_acceso.PruebaAccesoDirecto.test_ruta_relativa_se_absolutiza_antes_de_revisar` |
| `.cmd` ajeno intacto; sin inicio automático | `test_acceso.PruebaAccesoDirecto` |

## Operación v1 — parte D (instalación)

Spec `instalacion`.

| Escenario | Prueba |
|---|---|
| Simulación no escribe | `test_instalar.PruebaInstalarEscrituras.test_simulacion_no_escribe` |
| Idempotencia de `--aplicar` | `test_instalar.PruebaInstalarEscrituras.test_aplicar_idempotente` |
| Varias versiones de codex | `test_instalar.PruebaDeteccion.test_varias_versiones_de_codex_elige_la_mas_alta` |
| Empate de versión → carpeta más reciente | `test_instalar.PruebaDeteccion.test_empate_de_version_elige_carpeta_mas_reciente` |
| Cursor por existencia, sin ejecutar | `test_instalar.PruebaDeteccion.test_cursor_por_existencia_sin_ejecutarlo` |
| Git ausente | `test_instalar.PruebaDeteccion.test_git_ausente_queda_en_pendientes` |
| Claude sin sesión | `test_instalar.PruebaDeteccion.test_claude_sin_sesion` |
| Sin leer credenciales ni volcar salida | `test_instalar.PruebaDeteccion.test_sin_leer_credenciales_ni_volcar_salida` |
| Config existente intacto con pendiente | `test_instalar.PruebaInstalarEscrituras.test_config_existente_intacto_con_pendiente` |
| `.cmd` ajeno intacto | `test_instalar.PruebaInstalarEscrituras.test_cmd_ajeno_intacto` |
| Pendiente `no-push` | `test_instalar.PruebaInstalarEscrituras.test_pendiente_no_push` |
| Push anulado sin pendiente | `test_instalar.PruebaInstalarEscrituras.test_push_anulado_sin_pendiente` |
| Aviso al arrancar `orq correr` | `test_instalar.PruebaInstalarEscrituras.test_aviso_al_arrancar_orq_correr` |
| CLI `orq instalar` simula | `test_instalar.PruebaOrqInstalar.test_cli_instalar_simula` |
| Guía `docs/INSTALAR.md` al día | `test_instalar.PruebaGuiaInstalar.test_guia_al_dia` |
