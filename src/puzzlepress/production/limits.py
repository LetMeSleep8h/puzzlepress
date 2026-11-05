"""Resource limits a production worker applies to itself, and the peak it used.

Lower scheduling priority, so the Studio server and the rest of the machine stay
responsive while a book renders, and a memory ceiling, so one huge drawing cannot
exhaust the machine: an allocation past it fails as MemoryError, which the worker
reports as `memory_limit` without touching the release.

- Windows: the process assigns itself to a Job Object with a per-process committed
  memory limit, and sets BELOW_NORMAL priority.
- POSIX: `RLIMIT_AS` (address space, which counts more than resident memory) and
  `nice` 10.

Every limit is reported as applied or not, with the reason; nothing is assumed.
"""

from __future__ import annotations

import os
import sys

DEFAULT_MEMORY_MB = 4096
NICE = 10


if sys.platform == "win32":

    def apply_limits(memory_mb: int | None) -> dict[str, object]:
        """Lower this process's priority and cap its memory; report what took effect."""

        import ctypes
        from ctypes import wintypes

        report: dict[str, object] = {}
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.SetPriorityClass.restype = wintypes.BOOL
        process = kernel32.GetCurrentProcess()
        below_normal = 0x00004000
        if kernel32.SetPriorityClass(process, below_normal):
            report["priority"] = "below_normal"
        else:
            report["priority"] = f"not applied (Windows error {ctypes.get_last_error()})"
        if memory_mb is None:
            report["memory_mb"] = "not limited"
            return report

        class IoCounters(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_ulonglong)
                for name in ("read_ops", "write_ops", "other_ops", "read", "write", "other")
            ]

        class BasicLimits(ctypes.Structure):
            _fields_ = [
                ("per_process_user_time", ctypes.c_int64),
                ("per_job_user_time", ctypes.c_int64),
                ("flags", wintypes.DWORD),
                ("minimum_working_set", ctypes.c_size_t),
                ("maximum_working_set", ctypes.c_size_t),
                ("active_processes", wintypes.DWORD),
                ("affinity", ctypes.c_size_t),
                ("priority_class", wintypes.DWORD),
                ("scheduling_class", wintypes.DWORD),
            ]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [
                ("basic", BasicLimits),
                ("io", IoCounters),
                ("process_memory", ctypes.c_size_t),
                ("job_memory", ctypes.c_size_t),
                ("peak_process_memory", ctypes.c_size_t),
                ("peak_job_memory", ctypes.c_size_t),
            ]

        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            report["memory_mb"] = f"not applied (Windows error {ctypes.get_last_error()})"
            return report
        info = ExtendedLimits()
        info.basic.flags = 0x00000100  # JOB_OBJECT_LIMIT_PROCESS_MEMORY
        info.process_memory = memory_mb * 1024 * 1024
        extended_limit_information = 9
        if not kernel32.SetInformationJobObject(
            job, extended_limit_information, ctypes.byref(info), ctypes.sizeof(info)
        ) or not kernel32.AssignProcessToJobObject(job, process):
            report["memory_mb"] = f"not applied (Windows error {ctypes.get_last_error()})"
            return report
        # The handle stays open for the life of the process (the limit holds regardless).
        report["memory_mb"] = memory_mb
        return report

    def peak_memory_mb() -> float | None:
        """The most memory this process has held so far (Windows: peak committed bytes;
        POSIX: peak resident set), in MB; None when the platform does not say."""
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("page_faults", wintypes.DWORD),
                ("peak_working_set", ctypes.c_size_t),
                ("working_set", ctypes.c_size_t),
                ("quota_peak_paged", ctypes.c_size_t),
                ("quota_paged", ctypes.c_size_t),
                ("quota_peak_nonpaged", ctypes.c_size_t),
                ("quota_nonpaged", ctypes.c_size_t),
                ("pagefile", ctypes.c_size_t),
                ("peak_pagefile", ctypes.c_size_t),
            ]

        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        if not psapi.GetProcessMemoryInfo(
            kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        ):
            return None
        peak = max(int(counters.peak_working_set), int(counters.peak_pagefile))
        return round(peak / 1048576, 1)

else:

    def apply_limits(memory_mb: int | None) -> dict[str, object]:
        """Lower this process's priority and cap its memory; report what took effect."""

        import resource

        report: dict[str, object] = {}
        try:
            os.nice(NICE)
            report["priority"] = f"nice +{NICE}"
        except OSError as error:
            report["priority"] = f"not applied ({error})"
        if memory_mb is None:
            report["memory_mb"] = "not limited"
            return report
        limit = memory_mb * 1024 * 1024
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        if hard != resource.RLIM_INFINITY and hard < limit:
            limit = hard
        try:
            resource.setrlimit(resource.RLIMIT_AS, (limit, hard))
            report["memory_mb"] = limit // (1024 * 1024)
        except (OSError, ValueError) as error:
            report["memory_mb"] = f"not applied ({error})"
        del soft
        return report

    def peak_memory_mb() -> float | None:
        """The most memory this process has held so far (Windows: peak committed bytes;
        POSIX: peak resident set), in MB; None when the platform does not say."""
        import resource

        peak = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return round(peak / (1048576 if sys.platform == "darwin" else 1024), 1)
