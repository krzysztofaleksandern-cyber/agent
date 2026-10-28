"""Command execution in a disposable, locked-down Docker container."""

import asyncio
import contextlib
import logging
import os
import signal
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExecResult:
    exit_code: int
    output: str
    timed_out: bool = False
    truncated: bool = False

    def render(self) -> str:
        head = f"exit_code={self.exit_code}"
        if self.timed_out:
            head += " (timed out, killed)"
        if self.truncated:
            head += " (output truncated)"
        return f"{head}\n{self.output}"


class SandboxRunner(Protocol):
    async def run(
        self, command: str, workspace: Path, timeout_s: float | None = None, network: bool = False
    ) -> ExecResult: ...


class BoundedBuffer:
    """Keeps the first and last `limit // 2` bytes of a stream; drops the middle."""

    def __init__(self, limit: int) -> None:
        self.half = max(limit // 2, 1)
        self.head = bytearray()
        self.tail = bytearray()
        self.dropped = 0

    def feed(self, chunk: bytes) -> None:
        room = self.half - len(self.head)
        if room > 0:
            self.head += chunk[:room]
            chunk = chunk[room:]
        if not chunk:
            return
        self.tail += chunk
        overflow = len(self.tail) - self.half
        if overflow > 0:
            del self.tail[:overflow]
            self.dropped += overflow

    def text(self) -> tuple[str, bool]:
        head = self.head.decode(errors="replace")
        tail = self.tail.decode(errors="replace")
        if self.dropped:
            return f"{head}\n…[{self.dropped} bytes truncated]…\n{tail}", True
        return head + tail, False


async def _collect(stream: asyncio.StreamReader, buf: BoundedBuffer) -> None:
    while chunk := await stream.read(65536):
        buf.feed(chunk)


async def _exec_and_collect(
    args: list[str], cwd: Path | None, timeout_s: float, max_output: int, on_timeout: Any = None
) -> ExecResult:
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=cwd,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        start_new_session=True,  # own process group, so the whole tree can be killed
    )
    buf = BoundedBuffer(max_output)
    assert proc.stdout is not None
    timed_out = False
    try:
        await asyncio.wait_for(_collect(proc.stdout, buf), timeout_s)
        await proc.wait()
    except TimeoutError:
        timed_out = True
        if on_timeout is not None:
            await on_timeout()
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, signal.SIGKILL)
        await proc.wait()
    text, truncated = buf.text()
    code = proc.returncode if proc.returncode is not None else -1
    return ExecResult(exit_code=-1 if timed_out else code, output=text, timed_out=timed_out,
                      truncated=truncated)  # fmt: skip


class DockerSandbox:
    def __init__(
        self,
        image: str = "devagent-sandbox:latest",
        cpus: float = 1.0,
        memory: str = "1g",
        pids_limit: int = 256,
        timeout_s: float = 120.0,
        max_output: int = 20_000,
        docker_bin: str = "docker",
    ) -> None:
        self.image = image
        self.cpus = cpus
        self.memory = memory
        self.pids_limit = pids_limit
        self.timeout_s = timeout_s
        self.max_output = max_output
        self.docker_bin = docker_bin

    def build_args(self, command: str, workspace: Path, network: bool, name: str) -> list[str]:
        return [
            self.docker_bin, "run", "--rm", "--name", name,
            "--network", "bridge" if network else "none",
            "--cpus", str(self.cpus),
            "--memory", self.memory, "--memory-swap", self.memory,
            "--pids-limit", str(self.pids_limit),
            "--read-only", "--tmpfs", "/tmp:rw,exec,size=512m",  # noqa: S108 (container path)
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--user", "1000:1000", "-e", "HOME=/tmp",
            "-v", f"{workspace.resolve()}:/workspace:rw", "-w", "/workspace",
            self.image, "sh", "-lc", command,
        ]  # fmt: skip

    async def run(
        self, command: str, workspace: Path, timeout_s: float | None = None, network: bool = False
    ) -> ExecResult:
        name = f"devagent-{uuid.uuid4().hex[:12]}"
        args = self.build_args(command, workspace, network, name)

        async def kill() -> None:
            killer = await asyncio.create_subprocess_exec(
                self.docker_bin, "kill", name,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )  # fmt: skip
            await killer.wait()

        return await _exec_and_collect(
            args, None, timeout_s or self.timeout_s, self.max_output, on_timeout=kill
        )


class LocalRunner:
    """Runs commands directly on the host. NO isolation - development/testing only."""

    def __init__(self, timeout_s: float = 120.0, max_output: int = 20_000) -> None:
        self.timeout_s = timeout_s
        self.max_output = max_output

    async def run(
        self, command: str, workspace: Path, timeout_s: float | None = None, network: bool = False
    ) -> ExecResult:
        return await _exec_and_collect(
            ["sh", "-c", command], workspace, timeout_s or self.timeout_s, self.max_output
        )
