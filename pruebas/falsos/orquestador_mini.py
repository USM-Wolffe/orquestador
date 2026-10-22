"""Orquestador mínimo para la prueba "El orquestador muere": se ata a su Job, lanza el falso de cc en el Job de la
tarea, imprime el pid del agente y se queda esperando hasta que lo maten."""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from orquestador import procesos  # noqa: E402

procesos.atar_proceso_actual()
falso = sys.argv[1]
job = procesos.Job()
agente = subprocess.Popen([sys.executable, falso, "--como", "cc", "-p"], stdin=subprocess.PIPE,
                          stdout=subprocess.DEVNULL, creationflags=procesos.CREATE_NO_WINDOW)
job.asignar(agente)
agente.stdin.write(b"#guion: colgado\n")
agente.stdin.close()
print(agente.pid, flush=True)
time.sleep(600)
