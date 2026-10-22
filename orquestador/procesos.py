"""Procesos en Windows: Job Objects, hora de creación y terminación de árboles de procesos.

- Cada tarea corre en un Job Object con KILL_ON_JOB_CLOSE: cancelar o vencer el tiempo termina al agente y a sus
  hijos de una vez.
- `orq correr` se mete a sí mismo en un Job con KILL_ON_JOB_CLOSE: si muere, Windows cierra el handle y mueren
  todos sus descendientes.
- Si algo de esto falla, el respaldo es `taskkill /T /F` con la ruta absoluta de System32.
Solo librería estándar (ctypes).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

ES_WINDOWS = os.name == "nt"
CREATE_NO_WINDOW = 0x08000000

if ES_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in ("ReadOperationCount", "WriteOperationCount",
                                                       "OtherOperationCount", "ReadTransferCount",
                                                       "WriteTransferCount", "OtherTransferCount")]

    class _BASIC_LIMIT(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class _EXTENDED_LIMIT(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", _BASIC_LIMIT), ("IoInfo", _IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    class _FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

    _k32.CreateJobObjectW.restype = wintypes.HANDLE
    _k32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    _k32.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
    _k32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    _k32.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
    _k32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _k32.GetCurrentProcess.restype = wintypes.HANDLE
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _k32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    _k32.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(_FILETIME),) * 4
    _k32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)

    _EXTENDED_LIMIT_INFORMATION = 9
    _KILL_ON_JOB_CLOSE = 0x2000
    _QUERY_LIMITED = 0x1000
    _TERMINATE = 0x0001
    _STILL_ACTIVE = 259
    _ACCESS_DENIED = 5


class Job:
    """Job Object que termina a todos sus procesos cuando se cierra o se termina."""

    def __init__(self):
        self.handle = None
        if not ES_WINDOWS:
            return
        handle = _k32.CreateJobObjectW(None, None)
        if not handle:
            return
        info = _EXTENDED_LIMIT()
        info.BasicLimitInformation.LimitFlags = _KILL_ON_JOB_CLOSE
        if not _k32.SetInformationJobObject(handle, _EXTENDED_LIMIT_INFORMATION, ctypes.byref(info),
                                            ctypes.sizeof(info)):
            _k32.CloseHandle(handle)
            return
        self.handle = handle

    def asignar(self, proceso: subprocess.Popen) -> bool:
        if not self.handle:
            return False
        return bool(_k32.AssignProcessToJobObject(self.handle, int(proceso._handle)))

    def asignar_actual(self) -> bool:
        if not self.handle:
            return False
        return bool(_k32.AssignProcessToJobObject(self.handle, _k32.GetCurrentProcess()))

    def terminar(self, codigo: int = 1) -> bool:
        if not self.handle:
            return False
        return bool(_k32.TerminateJobObject(self.handle, codigo))

    def cerrar(self) -> None:
        if self.handle:
            _k32.CloseHandle(self.handle)
            self.handle = None


_JOB_PROPIO: Job | None = None


def atar_proceso_actual() -> bool:
    """Mete al proceso actual en un Job con KILL_ON_JOB_CLOSE. El handle queda abierto mientras viva el proceso."""
    global _JOB_PROPIO
    if _JOB_PROPIO is not None:
        return True
    job = Job()
    if job.asignar_actual():
        _JOB_PROPIO = job
        return True
    job.cerrar()
    return False


def hora_creacion(pid: int) -> int | None:
    """Hora de creación del proceso (FILETIME como entero), para distinguir un pid reutilizado."""
    if not ES_WINDOWS or not isinstance(pid, int) or pid <= 0:
        return None
    handle = _k32.OpenProcess(_QUERY_LIMITED, False, pid)
    if not handle:
        return None
    try:
        creacion, salida, kernel, usuario = _FILETIME(), _FILETIME(), _FILETIME(), _FILETIME()
        if not _k32.GetProcessTimes(handle, ctypes.byref(creacion), ctypes.byref(salida), ctypes.byref(kernel),
                                    ctypes.byref(usuario)):
            return None
        return (creacion.dwHighDateTime << 32) | creacion.dwLowDateTime
    finally:
        _k32.CloseHandle(handle)


def proceso_vivo(pid: int, creado: int | None = None) -> bool:
    """True si el proceso existe (y, si se da `creado`, si es el mismo y no un pid reutilizado).

    En Windows no se usa os.kill(pid, 0): con señal 0 Python llama a TerminateProcess.
    """
    if not isinstance(pid, int) or pid <= 0:
        return False
    if ES_WINDOWS:
        handle = _k32.OpenProcess(_QUERY_LIMITED, False, pid)
        if not handle:
            return ctypes.get_last_error() == _ACCESS_DENIED and creado is None
        try:
            codigo = wintypes.DWORD()
            if _k32.GetExitCodeProcess(handle, ctypes.byref(codigo)) and codigo.value != _STILL_ACTIVE:
                return False
        finally:
            _k32.CloseHandle(handle)
        return creado is None or hora_creacion(pid) == creado
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def terminar_pid(pid: int, arbol: bool = True) -> None:
    """Termina un proceso (y su árbol, con taskkill de System32 por ruta absoluta)."""
    if not ES_WINDOWS:
        try:
            os.kill(pid, 9)
        except OSError:
            pass
        return
    if arbol:
        taskkill = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "taskkill.exe"
        if taskkill.is_file():
            subprocess.run([str(taskkill), "/T", "/F", "/PID", str(pid)], capture_output=True,
                           creationflags=CREATE_NO_WINDOW, timeout=30)
            return
    handle = _k32.OpenProcess(_TERMINATE, False, pid)
    if handle:
        try:
            _k32.TerminateProcess(handle, 1)
        finally:
            _k32.CloseHandle(handle)
