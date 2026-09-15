from app.llama_client import LlamaClient


class FakeLlamaClient(LlamaClient):
    """LlamaClient whose answers are scripted instead of fetched. Each call
    to is_busy()/is_healthy() pops the next value from its list; the last
    value repeats once the list runs out."""

    def __init__(self, busy=None, healthy=None):
        # Deliberately don't call super().__init__: no real httpx client.
        self.busy_answers = list(busy or [None])
        self.healthy_answers = list(healthy or [None])
        self.calls: list[tuple[str, str, int]] = []

    async def aclose(self) -> None:
        pass

    def _next(self, answers):
        return answers.pop(0) if len(answers) > 1 else answers[0]

    async def is_busy(self, host, port):
        self.calls.append(("busy", host, port))
        return self._next(self.busy_answers)

    async def is_healthy(self, host, port):
        self.calls.append(("healthy", host, port))
        return self._next(self.healthy_answers)
