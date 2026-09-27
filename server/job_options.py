"""Validated, snapshotted processing options shared by CLI, jobs and subscriptions."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ProcessingOptions:
    backend: str = "qwen"
    skip_diarization: bool = True
    num_speakers: int | None = None

    def __post_init__(self) -> None:
        if self.backend not in {"qwen", "whisper", "mimo"}:
            raise ValueError("backend 必须是 qwen、whisper 或 mimo")
        if self.backend == "qwen" and (not self.skip_diarization or self.num_speakers is not None):
            raise ValueError("Qwen 不支持说话人分离，请选择 Whisper 或 MiMo")
        if not isinstance(self.skip_diarization, bool):
            raise ValueError("skip_diarization 必须是布尔值")
        if self.num_speakers is not None and (
            isinstance(self.num_speakers, bool)
            or not isinstance(self.num_speakers, int)
            or not 1 <= self.num_speakers <= 32
        ):
            raise ValueError("num_speakers 必须是 1 到 32 的整数")

    def to_dict(self) -> dict:
        return asdict(self)
