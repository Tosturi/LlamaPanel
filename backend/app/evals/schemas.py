from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class EvalSample(StrictModel):
    id: str = Field(min_length=1, max_length=200)
    system: str = Field(default="", max_length=32000)
    turns: list[str] = Field(min_length=1, max_length=100)
    answer: str | None = Field(default=None, max_length=32000)


class EvalSuite(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    scorer: Literal["exact_match", "numeric", "local_judge"]
    rubric: str = Field(default="", max_length=16000)
    samples: list[EvalSample] = Field(min_length=1, max_length=20000)

    @model_validator(mode="after")
    def check_samples(self):
        if len({s.id for s in self.samples}) != len(self.samples):
            raise ValueError("Sample IDs must be unique")
        if self.scorer == "local_judge" and not self.rubric:
            raise ValueError("A local-judge suite requires a scoring rubric")
        if self.scorer != "local_judge" and any(s.answer is None for s in self.samples):
            raise ValueError("Every sample requires an expected answer")
        if any(not t.strip() or len(t) > 32000 for s in self.samples for t in s.turns):
            raise ValueError("Turns must contain 1–32000 characters")
        return self


class EvalParticipant(StrictModel):
    preset: str = Field(min_length=1, max_length=120)
    runtime_id: str = "default"
    concurrency: int = Field(default=1, ge=1, le=32)
    max_tokens: int = Field(default=2048, ge=1, le=131072)
    temperature: float = Field(default=0, ge=0, le=2)
    ctx_size: int | None = Field(default=None, ge=512, le=2097152)
    batch_size: int | None = Field(default=None, ge=1, le=65536)
    ubatch_size: int | None = Field(default=None, ge=1, le=65536)
    calibrate: bool = False


class HarnessOptions(StrictModel):
    num_fewshot: int | None = Field(default=None, ge=0, le=100)
    apply_chat_template: bool = False
    max_length: int = Field(default=4096, ge=512, le=2097152)


class EvalRequest(StrictModel):
    engine: Literal["native", "lm-eval"] = "native"
    harness: HarnessOptions = Field(default_factory=HarnessOptions)
    name: str = Field(min_length=1, max_length=120)
    participants: list[EvalParticipant] = Field(min_length=1, max_length=8)
    benchmarks: list[str] = Field(min_length=1, max_length=20)
    sample_selection: Literal["full", "custom"] = "full"
    sample_limit: int | None = Field(default=None, ge=1, le=20000)
    seed: int = Field(default=42, ge=0, le=2147483647)
    judge: EvalParticipant | None = None
    stop_instances: list[str] = Field(default_factory=list)
    request_timeout: int = Field(default=600, ge=10, le=7200)
    load_timeout: int = Field(default=600, ge=10, le=7200)

    @model_validator(mode="after")
    def check_selection(self):
        if self.sample_selection == "custom" and self.sample_limit is None:
            raise ValueError("Custom selection requires a sample limit")
        if self.sample_selection == "full" and self.sample_limit is not None:
            raise ValueError("Full selection must not include a sample limit")
        if self.engine == "lm-eval":
            from app.evals.harness import TASKS

            if not set(self.benchmarks) <= {t["id"] for t in TASKS}:
                raise ValueError("Select a supported harness task")
            if self.judge or any(p.calibrate for p in self.participants):
                raise ValueError(
                    "Local judge and native throughput calibration are not used by harness"
                )
            if any(p.max_tokens >= self.harness.max_length for p in self.participants):
                raise ValueError("Max tokens must be smaller than Max sequence length")
        if any(
            p.batch_size and p.ubatch_size and p.ubatch_size > p.batch_size
            for p in self.participants
        ):
            raise ValueError("Micro-batch size cannot exceed Batch size")
        if len(set(self.benchmarks)) != len(self.benchmarks):
            raise ValueError("Select each benchmark once")
        return self


class ResumeRequest(StrictModel):
    concurrency: int | None = Field(default=None, ge=1, le=32)
    batch_size: int | None = Field(default=None, ge=1, le=65536)
    ubatch_size: int | None = Field(default=None, ge=1, le=65536)


class EvalStorage(StrictModel):
    directory: str = Field(min_length=1, max_length=4096)
