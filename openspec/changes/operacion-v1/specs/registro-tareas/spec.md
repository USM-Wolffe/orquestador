# Spec Delta

## MODIFIED Requirements

### Requirement: Campos mínimos de una tarea
Cada tarea SHALL tener: `id`, `titulo`, `prompt`, `agente`, `agentes_permitidos`, `estado`, `dependencias`,
`cambio`, `rama`, `gate`, `intentos`, `max_intentos`, `resultado`, `consumo`, `creada`, `actualizada`,
`iniciada`, `terminada` e `historial`. Puede tener además `base`, `red`, `prioridad`, `nueva_sesion`,
`timeout_min`, `no_antes_de`, `explicacion` y `revisa`.

#### Scenario: Tarea creada con lo mínimo
- **WHEN** Cowork crea una tarea con `id`, `titulo`, `prompt`, `agente` y `cambio`
- **THEN** el orquestador completa `agentes_permitidos` con `[agente]`, `dependencias` con `[]`, `rama` con el nombre del cambio, `gate` según `gate_por_defecto` del proyecto, `intentos` en 0, `max_intentos` en 3 y las marcas de tiempo

#### Scenario: Agente no permitido
- **WHEN** una tarea pide un agente que no está configurado, que no está habilitado o que el proyecto no permite
- **THEN** la solicitud se rechaza con un error de validación

#### Scenario: Explicación de la tarea
- **WHEN** Cowork crea una tarea con `explicacion` de hasta 300 caracteres sin saltos de línea
- **THEN** la tarea la guarda y el tablero la muestra como "Qué se aprueba"

#### Scenario: Explicación inválida
- **WHEN** `explicacion` pasa de 300 caracteres o trae caracteres de control
- **THEN** la solicitud se rechaza con un error de validación

## ADDED Requirements

### Requirement: Tarea de revisión
Una tarea con `revisa: <id>` SHALL ser la revisión de otra tarea del mismo cambio. El orquestador MUST rechazar
la solicitud si `<id>` no existe en el proyecto, es de otro cambio o es la misma tarea, y MUST agregar `<id>` a sus
dependencias. El veredicto se lee solo de la primera línea del informe de la revisión.

#### Scenario: Revisión válida
- **WHEN** Cowork crea T-4r con `revisa: "T-4"`, en el mismo cambio que T-4
- **THEN** T-4r queda con T-4 entre sus dependencias y el tablero muestra su veredicto en el gate correspondiente

#### Scenario: Revisión de otro cambio
- **WHEN** `revisa` apunta a una tarea de otro cambio
- **THEN** la solicitud se rechaza con un error de validación

#### Scenario: Veredicto
- **WHEN** el informe de T-4r empieza con `Veredicto: con reparos`
- **THEN** el veredicto es `con_reparos` y el resumen son los primeros 500 caracteres que siguen, redactados

#### Scenario: Informe sin veredicto
- **WHEN** la primera línea del informe no calza con `Veredicto: sin reparos|con reparos|no concluyente`
- **THEN** el veredicto es `no_concluyente`
