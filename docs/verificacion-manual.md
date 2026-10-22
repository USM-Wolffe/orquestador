# Verificación manual de E1 con el binario real

Lo que las pruebas automáticas no pueden cubrir porque usan el falso de cc. Se corre en PowerShell, en una
ventana y con un proyecto y un repo sintéticos (sin datos de clientes). Usa `openspec.cmd`, no `openspec`: la
política de ejecución bloquea los `.ps1`.

Variables de la sesión (ajusta la ruta si `claude.exe` está en otro lugar):

    $claude = "$env:USERPROFILE\.local\bin\claude.exe"
    $prueba = "$env:TEMP\orq-verificacion"
    New-Item -ItemType Directory -Force $prueba | Out-Null
    Set-Location $prueba

## 1. Versión y sesión

    & $claude --version
    & $claude auth status

Esperado: versión 2.1.302 o más nueva (verificada: 2.1.306) y sesión iniciada con la cuenta del plan (OAuth), sin
`ANTHROPIC_API_KEY` en el entorno: `Test-Path Env:ANTHROPIC_API_KEY` debe dar `False`.

## 2. `--restricted` con OAuth (decisión 7)

    "Responde solo: hola" | & $claude -p --output-format stream-json --verbose --permission-mode dontAsk --permission-prompts none --restricted --tools "Read"

Esperado: el evento `system/init` trae `"apiKeySource":"none"` y `"tools":["Read"]`, y el `result` final es
`hola` sin error de autenticación. Si falla por la autenticación, pon `"restricted": false` en
`agentes.cc` de `%USERPROFILE%\.orquestador\config.json` (respaldo: `--setting-sources user`) y anótalo.

## 3. `--permission-prompts none` con un comando negado

    [IO.File]::WriteAllText("$prueba\perfil.json", '{"permissions":{"defaultMode":"dontAsk","deny":["Bash(git push)","Bash(git push *)"]},"disableAllHooks":true}')
    "Ejecuta exactamente: git push origin main" | & $claude -p --output-format stream-json --verbose --permission-mode dontAsk --permission-prompts none --restricted --tools "Bash" --settings "$prueba\perfil.json"

Esperado: el proceso termina solo, sin quedarse esperando una respuesta, y el `result` trae `permission_denials`
con `git push origin main`. Si se queda esperando, córtalo con Ctrl+C y anótalo: es un bloqueo de E1.

## 4. Gate por botón en el navegador

Con un proyecto sintético (`py -3.12 .\orq.py proyecto nuevo demo --repo C:\ruta\al\repo-sintetico`) y desde la
carpeta del orquestador ya con commit (o agregando `--permitir-codigo-modificado` mientras pruebas):

    py -3.12 .\orq.py correr

En otra ventana, deja una tarea con gate:

    [IO.File]::WriteAllText("$env:USERPROFILE\Orquestador-Cowork\demo\entrada\01.json", '{"op":"crear","tareas":[{"id":"T-1","titulo":"Saludo","prompt":"Crea hola.txt con la palabra hola.","agente":"cc","cambio":"saludo","gate":{"requiere":true}}]}')

Esperado, en orden:
1. Al abrir el enlace de la terminal entras al tablero. Al abrirlo una segunda vez recibes 401.
2. En las herramientas del navegador (F12 → Aplicación → Cookies), `orq_sesion` aparece como `HttpOnly` y
   `SameSite=Strict`.
3. T-1 llega a `esperando_gate`. En su detalle ves el diff stat con `hola.txt` (nuevo), el informe y la huella corta.
4. Al pulsar **Aprobar**, la terminal muestra el código. Escríbelo y pulsa **Confirmar**: T-1 queda `hecha` y la
   terminal muestra la línea `[gate] demo/T-1 aprobada …`.
5. `py -3.12 .\orq.py estado` muestra T-1 como `hecha`.
6. Desde otra interfaz el tablero no responde:

       $ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike "127.*" } | Select-Object -First 1).IPAddress
       Test-NetConnection -ComputerName $ip -Port 8765

   Esperado: `TcpTestSucceeded : False`.

## 5. Conectar la carpeta de Cowork

En la app de Cowork conecta solo `%USERPROFILE%\Orquestador-Cowork\demo`. No conectes
`%USERPROFILE%\.orquestador`.

Esperado:
- Cowork ve `entrada\`, `respuestas\` y `salida\`.
- Una solicitud que Cowork deja en `entrada\` recibe su acuse en `respuestas\`.
- `salida\estado.json` muestra la tarea a más tardar 2 s después de cada cambio.
- Ningún archivo de `salida\` tiene el prompt completo ni secretos.

Revísalo así:

    Get-Content "$env:USERPROFILE\Orquestador-Cowork\demo\salida\estado.json" -Encoding utf8

## 6. Cierre

    py -3.12 -m unittest discover -s pruebas
    openspec.cmd validate orquestador-v1 --strict

Anota en el gate cualquier diferencia con lo esperado: texto exacto, versión de `claude` y hora.
