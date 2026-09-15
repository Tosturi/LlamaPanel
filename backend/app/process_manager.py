import asyncio
import time
from collections import deque
from typing import Optional

import psutil

from app.llama_client import LlamaClient
from app.schemas import FlagValue, ServerState, StatusResponse
from app.settings import Settings


class ProcessManager:
    """Owns the llama-server process state: start/stop, log capture, and
    live log fan-out to subscribers (e.g. websocket clients).

    Logs always go through settings.log_file rather than an in-memory PIPE.
    That's what lets an "adopted" process (one this panel instance didn't
    spawn - started manually, or left running by a previous panel run that
    has since exited) still stream logs: we just tail the same file its fds
    are already writing into.

    State machine:
        stopped -> starting -> running -> stopping -> stopped
                       |          |
                       +-> crashed <-+        (process exited on its own)

    "starting" is real, not cosmetic: the process has been spawned but
    llama-server's /health still answers 503 while it loads the model.
    Only once /health returns 200 does the state become "running".
    """

    READY_POLL_INTERVAL = 0.5

    def __init__(self, settings: Settings, client: LlamaClient) -> None:
        self._settings = settings
        self._client = client
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._pid: Optional[int] = None
        self._adopted = False
        self._state: ServerState = "stopped"
        self._model_id: Optional[str] = None
        self._args: list[str] = []
        self._flags: dict[str, FlagValue] = {}
        self._started_at: Optional[float] = None
        self._exit_code: Optional[int] = None
        self._log_buffer: deque[str] = deque(maxlen=settings.log_buffer_size)
        self._subscribers: set[asyncio.Queue] = set()
        self._stop_requested = False
        self._lock = asyncio.Lock()
        self._tail_task: Optional[asyncio.Task] = None
        self._ready_task: Optional[asyncio.Task] = None
        self._watch_task: Optional[asyncio.Task] = None
        self._pending_restart: Optional[dict] = None
        self._restart_task: Optional[asyncio.Task] = None

    @property
    def state(self) -> ServerState:
        return self._state

    @property
    def restart_pending(self) -> bool:
        return self._pending_restart is not None

    def _endpoint(self) -> tuple[str, int]:
        host = self._flags.get("host") or "127.0.0.1"
        port = self._flags.get("port") or 8080
        return str(host), int(port)

    async def is_busy(self) -> Optional[bool]:
        """Whether llama-server itself reports an in-flight generation right
        now (via its own /slots bookkeeping) - independent of who's talking
        to it (Hermes, the webui, ...)."""
        if self._state != "running":
            return False
        return await self._client.is_busy(*self._endpoint())

    async def status(self) -> StatusResponse:
        return StatusResponse(
            state=self._state,
            pid=self._pid,
            model_id=self._model_id,
            args=self._args or None,
            flags=self._flags or None,
            adopted=self._adopted,
            started_at=self._started_at,
            exit_code=self._exit_code,
            busy=await self.is_busy(),
            restart_pending=self.restart_pending,
        )

    # --- log fan-out -------------------------------------------------------

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

    # --- lifecycle ---------------------------------------------------------

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

            log_file = self._settings.log_file
            log_file.parent.mkdir(parents=True, exist_ok=True)
            banner = f"\n$ {binary} {' '.join(args)}\n"
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(banner)
            self._emit(banner.strip())

            log_fh = open(log_file, "a", encoding="utf-8")
            try:
                self._proc = await asyncio.create_subprocess_exec(
                    binary, *args, stdout=log_fh, stderr=log_fh,
                )
            except BaseException:
                self._state = "stopped"
                raise
            finally:
                log_fh.close()  # child already holds its own dup'd fd

            self._pid = self._proc.pid
            self._started_at = time.time()

            self._start_tail(from_start=False)
            self._watch_task = asyncio.create_task(self._watch_exit(self._proc))
            self._ready_task = asyncio.create_task(self._wait_until_ready(self._proc))

    async def _wait_until_ready(self, proc: asyncio.subprocess.Process) -> None:
        """Poll llama-server's /health until it stops answering 503 (model
        still loading). Bails out silently if the process we were waiting
        for is no longer the current one or has already left "starting"
        (crashed, or stop() was called mid-load)."""
        host, port = self._endpoint()
        try:
            while self._proc is proc and self._state == "starting":
                if await self._client.is_healthy(host, port):
                    if self._proc is proc and self._state == "starting":
                        self._state = "running"
                        self._emit("[llama-server is ready]")
                    return
                await asyncio.sleep(self.READY_POLL_INTERVAL)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._emit(f"[readiness check failed: {exc}]")

    def _start_tail(self, from_start: bool) -> None:
        """Replace the log tailer. The previous one must be cancelled
        explicitly: it only exits on its own when it observes a non-running
        state, and a restart flips stopped -> starting faster than its
        0.3s poll, so it would otherwise keep going and every line would be
        emitted twice (once per tailer)."""
        self._cancel_tail()
        self._tail_task = asyncio.create_task(self._tail_log_file(from_start=from_start))

    def _cancel_tail(self) -> None:
        self._tail_task = _cancel(self._tail_task)

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
        self._start_tail(from_start=True)
        self._watch_task = asyncio.create_task(self._watch_adopted())

    async def _tail_log_file(self, from_start: bool) -> None:
        path = self._settings.log_file
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
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._emit(f"[log tail error: {exc}]")

    async def _watch_exit(self, proc: asyncio.subprocess.Process) -> None:
        code = await proc.wait()
        if self._proc is not proc:
            return  # superseded by a newer start(); not our state to touch
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
            self._cancel_tail()
            self._ready_task = _cancel(self._ready_task)

            if self._adopted:
                await asyncio.to_thread(_terminate_pid, self._pid, timeout)
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

    async def restart(self, model_id: str, binary: str, args: list[str], flags: dict[str, FlagValue]) -> str:
        """Apply new flags by restarting llama-server - immediately if it's
        idle, or queued until its current generation finishes if not.
        Returns "applied" or "queued"."""
        pending = {"model_id": model_id, "binary": binary, "args": args, "flags": flags}

        if self._state != "running" or await self.is_busy() is not True:
            self._pending_restart = None
            await self.stop()
            await self.start(**pending)
            return "applied"

        self._pending_restart = pending
        self._emit("[reload requested - waiting for the current inference to finish]")
        if self._restart_task is None or self._restart_task.done():
            self._restart_task = asyncio.create_task(self._wait_and_restart())
        return "queued"

    async def cancel_restart(self) -> None:
        self._pending_restart = None
        self._restart_task = _cancel(self._restart_task)

    async def _wait_and_restart(self) -> None:
        try:
            while self._pending_restart is not None:
                if await self.is_busy() is not True:
                    pending = self._pending_restart
                    self._pending_restart = None
                    self._emit("[inference finished - reloading with the new settings]")
                    await self.stop()
                    await self.start(**pending)
                    return
                await asyncio.sleep(2.0)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self._pending_restart = None
            self._emit(f"[reload-when-idle failed: {exc}]")

    async def shutdown(self) -> None:
        """Panel is exiting. Deliberately leaves llama-server running: it's
        an independent long-lived process, and the next panel instance will
        adopt it via discovery. Only our own bookkeeping tasks are torn
        down so the event loop can close cleanly."""
        self._pending_restart = None
        for attr in ("_restart_task", "_ready_task", "_tail_task", "_watch_task"):
            setattr(self, attr, _cancel(getattr(self, attr)))
        # Give the cancelled tasks a tick to actually finish.
        await asyncio.sleep(0)


def _cancel(task: Optional[asyncio.Task]) -> None:
    """Cancel a task if it's still running; always returns None so callers
    can write `self._x = _cancel(self._x)`."""
    if task is not None and not task.done():
        task.cancel()
    return None


def _terminate_pid(pid: Optional[int], timeout: float) -> None:
    """Blocking terminate-then-kill for a process we don't own a handle to.
    Runs in a worker thread so psutil's wait() doesn't stall the loop."""
    if pid is None:
        return
    try:
        p = psutil.Process(pid)
        p.terminate()
        p.wait(timeout=timeout)
    except psutil.NoSuchProcess:
        pass
    except psutil.TimeoutExpired:
        p.kill()
