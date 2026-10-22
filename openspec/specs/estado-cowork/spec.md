# estado-cowork Specification

## Purpose
Le da a Cowork una carpeta propia, que Sebastian conecta en la app, donde escribe solicitudes y lee una copia del
estado (tareas, eventos, resultados y consumo) sin secretos, sin datos de archivos y sin exponer el resto del
estado del orquestador.

## Requirements

### Requirement: Carpeta de Cowork fuera de la raíz de estado
Cada proyecto SHALL tener su carpeta de Cowork en `<cowork_raiz>\<proyecto>\` (por defecto
`%USERPROFILE%\Orquestador-Cowork`), con solo `entrada\`, `respuestas\` y `salida\`. El orquestador MUST negarse a
iniciar si `cowork_raiz` queda dentro de la raíz de estado, la raíz de estado dentro de `cowork_raiz`, o
cualquiera de las dos dentro de un repo registrado.

#### Scenario: Carpetas por defecto
- **WHEN** se crea el proyecto `demo` sin configurar `cowork_raiz`
- **THEN** existe `%USERPROFILE%\Orquestador-Cowork\demo\` con `entrada\`, `respuestas\` y `salida\`, y nada más

#### Scenario: Carpeta de Cowork dentro de la raíz de estado
- **WHEN** `cowork_raiz` apunta a una subcarpeta de la raíz de estado
- **THEN** el orquestador termina con un error de configuración y no escribe nada

### Requirement: Salida de solo lectura actualizada por el orquestador
El orquestador SHALL mantener en `salida\` los archivos `estado.json` (tareas, agentes y latido),
`eventos-recientes.json` (últimos 300 eventos), `consumo.json` (totales por agente y día), `resultados\<id>.md` y
`diffstat\<id>.json`, con escritura atómica y como máximo 2 segundos después de cada cambio.

#### Scenario: Cowork lee el avance
- **WHEN** una tarea pasa a `esperando_gate`
- **THEN** a más tardar 2 segundos después, `salida\estado.json` muestra el nuevo estado y la huella corta, y `salida\resultados\<id>.md` tiene la respuesta del agente

#### Scenario: Eventos recientes acotados
- **WHEN** el proyecto lleva 5.000 eventos
- **THEN** `salida\eventos-recientes.json` trae solo los últimos 300, con textos de 500 caracteres o menos

### Requirement: Salida sin secretos ni datos
La salida para Cowork MUST armarse solo con campos de lista blanca ya redactados, y MUST NOT incluir contenido de
archivos, salidas de comandos, stderr, el prompt completo (solo su hash), tokens del tablero, códigos de gate,
rutas absolutas fuera del worktree ni la configuración del orquestador o de los agentes.

#### Scenario: Secretos sembrados
- **WHEN** una prueba pone secretos sintéticos en el entorno del orquestador, en el prompt, en el stderr del agente y en un comando que el agente corre
- **THEN** ninguno aparece en ningún archivo de `salida\`

#### Scenario: Archivo de datos leído por el agente
- **WHEN** el agente lee `datos/clientes.csv`
- **THEN** `salida\` solo muestra el evento con la ruta relativa, nunca el contenido

### Requirement: El orquestador nunca lee la salida
El orquestador SHALL tratar `salida\` como solo de escritura para él: MUST NOT leerla como fuente de verdad, y si
Cowork o alguien más la modifica, la reescribe en el siguiente ciclo.

#### Scenario: Cowork edita la salida
- **WHEN** alguien cambia el estado de una tarea dentro de `salida\estado.json`
- **THEN** el registro no cambia y `salida\estado.json` vuelve a mostrar el estado real en el siguiente ciclo
