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
    openspec.cmd validate operacion-v1 --strict

Anota en el gate cualquier diferencia con lo esperado: texto exacto, versión de `claude` y hora.

## 7. Conectores de claude.ai

Lo corre Sebastian (tarea 1.5). Anota versión, hora, comando, `tools` y `mcp_servers` de cada intento,
y qué capa basta sola. Todos los prompts son `Responde solo: hola`; no se pide usar herramientas.
Cierra otras sesiones de prueba. Conserva el valor anterior de la variable y restáuralo al terminar.
El perfil mínimo de las pruebas aisladas no reemplaza el perfil de seguridad del adaptador.

Preparación y lectura de NDJSON (cada línea se convierte por separado):

```powershell
$anteriorMcp = $env:ENABLE_CLAUDEAI_MCP_SERVERS
Remove-Item Env:ENABLE_CLAUDEAI_MCP_SERVERS -ErrorAction SilentlyContinue
$base = @('-p', '--output-format', 'stream-json', '--verbose', '--permission-mode', 'dontAsk', '--permission-prompts', 'none', '--restricted', '--tools', 'Read')
function Ver-Inicio {
    process {
        $evento = $_ | ConvertFrom-Json
        if ($evento.type -eq 'system' -and $evento.subtype -eq 'init') {
            $evento | Select-Object tools, mcp_servers | ConvertTo-Json -Depth 8
        }
        if ($evento.type -eq 'rate_limit_event') {
            $evento.rate_limit_info | Select-Object status, utilization, resetsAt | ConvertTo-Json
        }
    }
}
```

### (a) Comando del hallazgo (paso 2)

```powershell
'Responde solo: hola' | & $claude @base | Ver-Inicio
```

Anota incluso herramientas propias como `EndConversation`. El resultado establece la comparación de (b) a (e).

### (b) Solo `--strict-mcp-config`

```powershell
'Responde solo: hola' | & $claude @base --strict-mcp-config | Ver-Inicio
```

### (c) Solo variable de entorno

```powershell
$env:ENABLE_CLAUDEAI_MCP_SERVERS = 'false'
'Responde solo: hola' | & $claude @base | Ver-Inicio
Remove-Item Env:ENABLE_CLAUDEAI_MCP_SERVERS
```

### (d) Solo `disableClaudeAiConnectors` desde `--settings`

```powershell
[IO.File]::WriteAllText("$prueba\solo-conectores.json", '{"disableClaudeAiConnectors":true}')
'Responde solo: hola' | & $claude @base --settings "$prueba\solo-conectores.json" | Ver-Inicio
```

### (e) Solo `--disallowedTools mcp__*`

```powershell
'Responde solo: hola' | & $claude @base --disallowedTools 'mcp__*' | Ver-Inicio
```

Comprueba además la quinta capa, `permissions.deny`, sola:

```powershell
[IO.File]::WriteAllText("$prueba\solo-deny.json", '{"permissions":{"deny":["mcp__*"]}}')
'Responde solo: hola' | & $claude @base --settings "$prueba\solo-deny.json" | Ver-Inicio
```

### (f) Comando completo del adaptador

Desde el repo, genera el mismo perfil que usa el adaptador para el proyecto sintético `demo`:

```powershell
py -3.12 -c "from orquestador.config import cargar_config; from orquestador.proyectos import cargar_proyectos; from orquestador.adaptadores.cc import perfil; import json, pathlib, sys; c=cargar_config(); p=next(p for p in cargar_proyectos(c) if p.nombre=='demo'); pathlib.Path(sys.argv[1]).write_text(json.dumps(perfil(c,p,False)),encoding='utf-8')" "$prueba\perfil-completo.json"
$env:ENABLE_CLAUDEAI_MCP_SERVERS = 'false'
$env:CLAUDE_CODE_SUBPROCESS_ENV_SCRUB = '1'
$env:DISABLE_AUTOUPDATER = '1'
$sesion = [guid]::NewGuid().ToString()
'Responde solo: hola' | & $claude -p --output-format stream-json --verbose --permission-mode dontAsk --permission-prompts none --restricted --tools 'Read,Edit,Write,Glob,Grep,Bash,TodoWrite,Skill' --settings "$prueba\perfil-completo.json" --strict-mcp-config --disallowedTools 'mcp__*' --session-id $sesion | Ver-Inicio
```

Si `restricted` está desactivado en la config, reemplaza `--restricted` por `--setting-sources user`.
Esperado: `mcp_servers` vacío y `tools` solo con las pedidas más las propias verificadas. Llena
`HERRAMIENTAS_TOLERADAS` en `cc.py` con versión y fecha por nombre; nunca toleres un nombre `mcp__`.
Hasta completar esa verificación, una herramienta propia desconocida detiene la tarea por seguridad.
La vigilancia de `tool_use` detecta: no garantiza que la llamada no haya empezado.

### (g) Tarea real por el orquestador

Con `orq.py correr` activo y el proyecto sintético `demo`, crea una tarea con prompt `Responde solo: hola`
por la entrada de Cowork como en el paso 4 (id nuevo). Revisa sus eventos:

```powershell
Get-Content "$env:USERPROFILE\.orquestador\proyectos\demo\eventos\eventos.jsonl" -Encoding utf8 | ForEach-Object {
    $evento = $_ | ConvertFrom-Json
    if ($evento.tipo -in @('inicio', 'error', 'fin')) { $evento | ConvertTo-Json -Depth 8 }
}
```

Esperado: llega a `fin` con `ok: true`, sin error de clase `seguridad`, y el `inicio` no contiene ningún `mcp__`.

### (h) Escala de `utilization`

Los comandos anteriores imprimen también cada `rate_limit_event`. Anota valor crudo de `utilization`,
`status`, `resetsAt`, hora y ventana si se informa; contrasta con el uso visible del plan. Si no llega,
anota «sin dato»; no estimes la escala ni un porcentaje. No se implementa aquí el uso del plan (parte B).

```powershell
if ($null -eq $anteriorMcp) {
    Remove-Item Env:ENABLE_CLAUDEAI_MCP_SERVERS -ErrorAction SilentlyContinue
} else {
    $env:ENABLE_CLAUDEAI_MCP_SERVERS = $anteriorMcp
}
```
