from __future__ import annotations

import os
import shutil
import signal
import subprocess
from pathlib import Path
from typing import IO, Sequence

from pystarport.utils import wait_for_port


def require_binary(binary: str) -> None:
    """Raise a skip-friendly ``FileNotFoundError`` if ``binary`` isn't on $PATH."""
    if shutil.which(binary) is None:
        raise FileNotFoundError(
            f"{binary!r} not found on $PATH — run inside `nix develop`"
        )


class ManagedProcess:
    """A spawned sidecar: its own process group, a captured log, and a ``stop``
    that escalates SIGTERM→SIGKILL across the group."""

    def __init__(self, proc: subprocess.Popen, log: IO, log_path: Path) -> None:
        self.proc = proc
        self.log_path = log_path
        self._log = log

    @classmethod
    def spawn(
        cls, argv: Sequence[str], *, log_path: Path, wait_port: int, name: str
    ) -> ManagedProcess:
        """Spawn ``argv`` in its own session, logging to ``log_path``, then wait
        for ``wait_port`` to bind. Tears down + raises ``RuntimeError`` on timeout.
        """
        log = log_path.open("w")
        proc = subprocess.Popen(
            list(argv), stdout=log, stderr=subprocess.STDOUT, preexec_fn=os.setsid
        )
        managed = cls(proc, log, log_path)
        try:
            wait_for_port(wait_port)
        except TimeoutError:
            managed.stop()
            raise RuntimeError(f"{name} didn't start; see {log_path}")
        return managed

    def stop(self) -> None:
        if self.proc.poll() is None:
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
                self.proc.wait(timeout=10)
            except ProcessLookupError:
                pass
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
                self.proc.wait()
        if not self._log.closed:
            self._log.close()
