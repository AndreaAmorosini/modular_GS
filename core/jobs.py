"""
JobManager: lato-server process registry for the web GUI.

Runs long-lived subprocesses (pipeline runs, method installs, validations)
independently of any browser session, keeping a bounded in-memory log buffer
per job that can be streamed to clients via the WebSocket endpoints exposed
in core.gui.server.
"""

import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Dict, List, Optional


LOG_BUFFER_SIZE = 10000
MAX_JOBS_HISTORY = 60
STOP_GRACE_SECONDS = 5.0


class Job:
    def __init__(
        self,
        id: str,
        kind: str,
        name: str,
        command: List[str],
        cwd: str,
        tmp_files: Optional[List[Path]] = None,
    ):
        self.id = id
        self.kind = kind              # "pipeline" | "method" | "help"
        self.name = name
        self.command = command
        self.cwd = str(cwd)
        self.status = "running"       # "running" | "success" | "failed" | "stopped"
        self.returncode: Optional[int] = None
        self.pid: Optional[int] = None
        self.start_time = time.time()
        self.end_time: Optional[float] = None
        self.tmp_files: List[Path] = tmp_files or []
        self._logs: deque = deque(maxlen=LOG_BUFFER_SIZE)
        self._log_lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._total = 0               # total lines ever produced
        self._dropped = 0             # lines evicted from the bounded buffer

    def append_log(self, line: str):
        with self._log_lock:
            self._logs.append(line.rstrip("\n"))
            self._total += 1
            if self._total > len(self._logs):
                self._dropped = self._total - len(self._logs)

    def read_since(self, cursor: int):
        """Return (lines, new_cursor). Cursor is a monotonically growing index."""
        with self._log_lock:
            if cursor >= self._total:
                return [], self._total
            start = max(0, cursor - self._dropped)
            lines = list(self._logs)[start:]
            return lines, self._total

    def snapshot(self) -> dict:
        duration = (self.end_time or time.time()) - self.start_time
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "command": self.command,
            "status": self.status,
            "returncode": self.returncode,
            "pid": self.pid,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_s": round(duration, 2),
            "log_lines": self._total,
        }


class JobManager:
    """Singleton registry of background subprocess jobs."""

    _instance = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(
        self,
        kind: str,
        name: str,
        command: List[str],
        cwd: str,
        tmp_files: Optional[List[Path]] = None,
    ) -> Job:
        job = Job(
            id=uuid.uuid4().hex[:12],
            kind=kind,
            name=name,
            command=command,
            cwd=cwd,
            tmp_files=tmp_files,
        )

        proc = subprocess.Popen(
            command,
            cwd=job.cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            start_new_session=True,
        )
        job._proc = proc
        job.pid = proc.pid

        with self._lock:
            self._jobs[job.id] = job
            self._prune_history()

        threading.Thread(target=self._watch, args=(job,), daemon=True).start()
        return job

    def _watch(self, job: Job):
        proc = job._proc
        try:
            for line in iter(proc.stdout.readline, ""):
                if line:
                    job.append_log(line)
            proc.stdout.close()
            returncode = proc.wait()
        except Exception as e:
            job.append_log(f"[jobmanager] reader error: {e}")
            returncode = -1
        finally:
            job.returncode = returncode
            job.end_time = time.time()
            if job.status == "running":
                job.status = "success" if returncode == 0 else "failed"
            self._cleanup_tmp(job)

    def stop(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job or job.status != "running" or not job._proc:
            return False
        job.status = "stopped"
        proc = job._proc

        def _terminate():
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                return
            deadline = time.time() + STOP_GRACE_SECONDS
            while time.time() < deadline and proc.poll() is None:
                time.sleep(0.2)
            if proc.poll() is None:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass

        threading.Thread(target=_terminate, daemon=True).start()
        return True

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def list(self, kind: Optional[str] = None) -> List[dict]:
        with self._lock:
            jobs = list(self._jobs.values())
        if kind:
            jobs = [j for j in jobs if j.kind == kind]
        return [j.snapshot() for j in sorted(jobs, key=lambda j: j.start_time, reverse=True)]

    def running_count(self, kind: Optional[str] = None) -> int:
        return sum(1 for j in self.list(kind) if j["status"] == "running")

    def _prune_history(self):
        overflow = len(self._jobs) - MAX_JOBS_HISTORY
        if overflow <= 0:
            return
        finished = sorted(
            (j for j in self._jobs.values() if j.status != "running"),
            key=lambda j: j.end_time or 0,
        )
        for job in finished[:overflow]:
            self._cleanup_tmp(job)
            self._jobs.pop(job.id, None)

    @staticmethod
    def _cleanup_tmp(job: Job):
        for tmp in job.tmp_files:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
        job.tmp_files = []


def python_executable() -> str:
    return sys.executable
