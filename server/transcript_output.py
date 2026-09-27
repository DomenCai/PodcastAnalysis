"""Build the stable, human-readable speaker transcript output."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any


def _speaker_key(turn: Mapping[str, Any]) -> Any:
    """Return a hashable identity for a turn's speaker."""
    speaker = turn.get("speaker")
    if speaker is None or speaker == "":
        return "UNKNOWN"
    try:
        hash(speaker)
    except TypeError:
        return repr(speaker)
    return speaker


def add_speaker_labels(
    turns: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Copy turns and label speakers in their order of first appearance.

    The input mappings are never mutated. Missing speaker IDs are treated as one
    (unknown) speaker, which keeps output deterministic for incomplete results.
    """
    labels: dict[Any, str] = {}
    labelled_turns: list[dict[str, Any]] = []
    speakers = {_speaker_key(turn) for turn in turns}
    show_speaker_labels = len(speakers) >= 2

    for turn in turns:
        speaker = _speaker_key(turn)
        if speaker != "UNKNOWN" and speaker not in labels:
            labels[speaker] = f"发言人 {len(labels) + 1}"
        labelled_turn = dict(turn)
        if show_speaker_labels:
            labelled_turn["speaker_label"] = (
                "未知发言人" if speaker == "UNKNOWN" else labels[speaker]
            )
        else:
            # A one-speaker transcript should not expose a meaningless
            # "发言人 1" label in either JSON or human-readable output.
            labelled_turn.pop("speaker_label", None)
            labelled_turn.pop("speaker_name", None)
        labelled_turns.append(labelled_turn)

    return labelled_turns


def _format_timestamp(value: Any) -> str:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        seconds = 0.0
    if not math.isfinite(seconds) or seconds < 0:
        seconds = 0.0

    total_seconds = int(seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def build_formatted_text(turns: Sequence[Mapping[str, Any]]) -> str:
    """Render turns with speaker labels only when there are at least two speakers."""
    lines: list[str] = []
    for turn in add_speaker_labels(turns):
        text = turn.get("text")
        if text is None:
            continue
        # Keep one physical output line per speaker turn.
        text = " ".join(str(text).split())
        if not text:
            continue
        timestamp = _format_timestamp(turn.get("start"))
        speaker_label = turn.get("speaker_label")
        prefix = f"[{timestamp} {speaker_label}]" if speaker_label else f"[{timestamp}]"
        lines.append(f"{prefix} {text}")
    return "\n".join(lines)
