# Spec Delta

## Purpose

Permite que Sebastian abra el tablero con un doble clic o desde la ventana del orquestador, sin copiar enlaces y
sin crear un canal nuevo por el que otro proceso del mismo usuario pueda pedir una sesión.

## ADDED Requirements

### Requirement: Abrir el navegador al arrancar
`orq correr --abrir` SHALL abrir el navegador predeterminado con el enlace de entrada vigente apenas el tablero
escuche. Sin `--abrir`, el comportamiento MUST ser el de siempre: solo se muestra el enlace en la terminal.

#### Scenario: Arranque con --abrir
- **WHEN** Sebastian corre `orq correr --abrir`
- **THEN** el navegador se abre con `/entrar?t=<token>`, el canje deja la sesión abierta y la terminal muestra el aviso de sesión nueva

#### Scenario: Con --sin-tablero
- **WHEN** se corre `orq correr --abrir --sin-tablero`
- **THEN** el orquestador termina con un error que dice que las dos opciones no se combinan, sin abrir ningún puerto

### Requirement: Enlace nuevo desde la terminal
Mientras corre con tablero, el orquestador SHALL leer la entrada de su propia terminal: cada Enter genera un enlace
de entrada nuevo, lo muestra en la terminal y abre el navegador con él. Es la única forma de pedir un enlace
nuevo, y MUST NOT existir otra vía (archivo, tubería, puerto o ruta HTTP) para pedirlo.

#### Scenario: Pulsar Enter
- **WHEN** Sebastian pulsa Enter en la ventana de `orq correr`
- **THEN** la terminal muestra un enlace nuevo, se abre el navegador con él y el enlace anterior sin canjear deja de servir

#### Scenario: Cerrar todas las sesiones
- **WHEN** Sebastian escribe `x` y pulsa Enter en la ventana de `orq correr`
- **THEN** toda sesión abierta deja de servir (la siguiente petición con su cookie recibe 401) y la terminal lo confirma

#### Scenario: Sin terminal interactiva
- **WHEN** `orq correr` corre con la entrada estándar redirigida o cerrada
- **THEN** el orquestador sigue funcionando, no genera enlaces nuevos y lo avisa una vez en la terminal

#### Scenario: Ninguna otra vía
- **WHEN** las pruebas buscan, con el orquestador corriendo, tuberías con nombre, archivos o rutas HTTP que entreguen un enlace o una sesión
- **THEN** no encuentran ninguno: `/entrar` solo canjea y ninguna otra ruta crea tokens

### Requirement: orq abrir
`orq abrir` SHALL abrir el navegador en `http://127.0.0.1:<puerto>/` sin token si el orquestador está corriendo
según el candado (que guarda el puerto del tablero), y mostrar en la consola que, si el tablero pide entrar, hay
que pulsar Enter en la ventana del orquestador. Si el orquestador no corre, MUST decirlo y terminar sin abrir nada.
Nunca MUST obtener ni mostrar un token, y MUST NOT escribir nada.

#### Scenario: Orquestador corriendo
- **WHEN** Sebastian corre `orq abrir` con `orq correr` vivo según el candado
- **THEN** se abre `http://127.0.0.1:<puerto>/` y la consola muestra la instrucción del Enter

#### Scenario: Orquestador detenido
- **WHEN** no hay candado vivo
- **THEN** `orq abrir` dice "El orquestador no está corriendo: usa el acceso directo o `orq correr --abrir`" y termina con código 1

### Requirement: Acceso directo del escritorio
El repo SHALL poder generar `Orquestador.cmd` en la carpeta real del escritorio del usuario. El archivo arranca
`orq correr --abrir` con rutas absolutas de Python y del repo, deja la ventana abierta si el orquestador termina
con error y no depende de nada fuera de Windows y Python. No MUST registrarse para arrancar con Windows.

#### Scenario: Doble clic
- **WHEN** Sebastian hace doble clic en `Orquestador.cmd` con el orquestador detenido
- **THEN** se abre una ventana titulada "Orquestador" que corre `orq correr --abrir`, y el navegador abre el tablero con la sesión

#### Scenario: Ya estaba corriendo
- **WHEN** se hace doble clic con otro `orq correr` vivo
- **THEN** la ventana nueva informa que ya hay uno corriendo, hace lo mismo que `orq abrir` y queda esperando una tecla antes de cerrarse

#### Scenario: Rutas con espacios y tildes
- **WHEN** el repo está en `C:\Users\José Pérez\work\orquestador` y Python en una ruta con espacios
- **THEN** el `.cmd` generado funciona igual al ejecutarlo con `cmd.exe`

#### Scenario: Rutas que no se pueden escribir con seguridad
- **WHEN** alguna ruta trae `%`, `"`, `!`, `^` o saltos de línea
- **THEN** no se genera el `.cmd` y el motivo queda en la lista de pendientes

#### Scenario: Sin inicio automático
- **WHEN** se genera el acceso directo
- **THEN** no se escribe nada en la carpeta de Inicio, el registro `Run` ni el Programador de tareas
