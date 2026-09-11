import asyncio
import time
from collections import deque
from typing import Optional

import psutil

from app import config
from app.schemas import FlagValue, ServerState, StatusResponse


class ProcessManager:
    """Owns the llama-server process state: start/stop, log capture, and
    live log fan-out to subscribers (e.g. websocket clients).

    Logs always go through config.LOG_FILE rather than an in-memory PIPE.
    That's what lets an "adopted" process (one this panel instance didn't
    spawn - started manually, or left running by a previous panel run that
    has since exited) still stream logs: we just tail the same file its fds
    are already writing into.
    """

    def __init__(self) -> None:
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._pid: Optional[int] = None
        self._adopted = False
        self._state: ServerState = "stopped"
        self._model_id: Optional[str] = None
        self._args: list[str] = []
        self._flags: dict[str, FlagValue] = {}
        self._started_at: Optional[float] = None
        self._exit_code: Optional[int] = None
        self._log_buffer: deque[str] = deque(maxlen=config.LOG_BUFFER_SIZE)
        self._subscribers: set[asyncio.Queue] = set()
        self._stop_requested = False
        self._lock = asyncio.Lock()
        self._tail_task: Optional[asyncio.Task] = None

    @property
    def state(self) -> ServerState:
        return self._state

    def status(self) -> StatusResponse:
        return StatusResponse(
            state=self._state,
            pid=self._pid,
            model_id=self._model_id,
            args=self._args or None,
            flags=self._flags or None,
            adopted=self._adopted,
            started_at=self._started_at,
            exit_code=self._exit_code,
        )

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subscribers.add(q)
        for line in self._log_buffer:
            q.put_nowait(line)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def _emit(self, line: str) -> None:
        self._log_buffer.append(line)
        for q in list(self._subscribers):
            try:
                q.put_nowait(line)
            except asyncio.QueueFull:
                pass

    async def start(self, model_id: str, binary: str, args: list[str], flags: dict[str, FlagValue]) -> None:
        async with self._lock:
            if self._state in ("starting", "running"):
                raise RuntimeError(f"Server is already {self._state}")

            self._state = "starting"
            self._model_id = model_id
            self._args = args
            self._flags = flags
            self._exit_code = None
            self._stop_requested = False
            self._adopted = False

            config.LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            banner = f"\n$ {binary} {' '.join(args)}\n"
            with open(config.LOG_FILE, "a", encoding="utf-8") as f:
                f.write(banner)
            self._emit(banner.strip())

            log_fh = open(config.LOG_FILE, "a", encoding="utf-8")
            try:
                self._proc = await asyncio.create_subprocess_exec(
                    binary, *args, stdout=log_fh, stderr=log_fh,
                )
            finally:
                log_fh.close()  # child already holds its own dup'd fd

            self._pid = self._proc.pid
            self._started_at = time.time()
            self._state = "running"

            self._tail_task = asyncio.create_task(self._tail_log_file(from_start=False))
            asyncio.create_task(self._watch_exit())

    def adopt(self, pid: int, model_id: Optional[str], flags: dict[str, FlagValue]) -> None:
        """Recognize an already-running llama-server this panel didn't spawn."""
        if self._state in ("running", "starting"):
            return
        self._proc = None
        self._pid = pid
        self._adopted = True
        self._model_id = model_id
        self._args = []
        self._flags = flags
        self._exit_code = None
        self._started_at = None
        self._state = "running"
        self._emit(f"[adopted already-running llama-server, pid={pid}]")
        self._tail_task = asyncio.create_task(self._tail_log_file(from_start=True))
        asyncio.create_task(self._watch_adopted())

    async def _tail_log_file(self, from_start: bool) -> None:
        path = config.LOG_FILE
        try:
            while not path.exists():
                await asyncio.sleep(0.2)
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                if not from_start:
                    f.seek(0, 2)  # only lines written from now on
                while True:
                    line = f.readline()
                    if line:
                        self._emit(line.rstrip("\n"))
                    elif self._state in ("running", "starting"):
                        await asyncio.sleep(0.3)
                    else:
                        break
        except Exception as exc:
            self._emit(f"[log tail error: {exc}]")

    async def _watch_exit(self) -> None:
        proc = self._proc
        assert proc is not None
        code = await proc.wait()
        self._exit_code = code
        self._state = "stopped" if self._stop_requested else "crashed"
        if not self._stop_requested:
            self._emit(f"[process exited unexpectedly with code {code}]")

    async def _watch_adopted(self) -> None:
        while self._adopted and self._state == "running":
            if not psutil.pid_exists(self._pid):
                self._state = "stopped" if self._stop_requested else "crashed"
                self._emit(f"[adopted process pid={self._pid} is gone]")
                return
            await asyncio.sleep(2.0)

    async def stop(self, timeout: float = 10.0) -> None:
        async with self._lock:
            if self._state not in ("running", "starting"):
                return
            self._state = "stopping"
            self._stop_requested = True

            if self._adopted:
                try:
                    p = psutil.Process(self._pid)
                    p.terminate()
                    p.wait(timeout=timeout)
                except psutil.NoSuchProcess:
                    pass
                except psutil.TimeoutExpired:
                    p.kill()
                self._state = "stopped"
                self._adopted = False
                return

            proc = self._proc
            if proc is None:
                self._state = "stopped"
                return

            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                self._emit("[graceful shutdown timed out, killing process]")
                proc.kill()
                await proc.wait()

            self._state = "stopped"


manager = ProcessManager()
