"""使用 OpenAI-compatible API 对说话人轮次做受约束的文本后处理。

处理分为两个独立阶段：先用可审计 patch 纠正错字，再只补标点。模型不能
修改、合并或重新判断 speaker；输入 turn 的其他字段也会原样保留。
"""

from __future__ import annotations

import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Callable, Sequence
from copy import deepcopy
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

DEFAULT_BASE_URL = "https://cpa.domencai.top/v1"
DEFAULT_MODEL = "qwen3.8-27b"
DEFAULT_CHUNK_CHARS = 800
# 模型上下文上限为 8000。这里按字符数做保守预算，并给 system prompt、JSON
# 包装和输出预留余量；不要把这个值直接调到模型的理论上限。
MAX_CORRECTION_CHUNK_CHARS = 2400
MAX_PUNCTUATION_CHUNK_CHARS = 1600
MAX_REVIEW_CANDIDATE_CHARS = 4200
MAX_CONTEXT_BUDGET = 7600
MAX_PARTS_PER_CHUNK = 64
# 逐字稿优先提高召回率；最终是否应用仍由本地硬校验和风险审计决定。
MIN_CORRECTION_CONFIDENCE = 0.85

# 只用于判断“已知官方拼写”是否可以跳过二次 LLM 审计，不用于盲目替换。
# 未收录的专名仍然会进入审计流程。
OFFICIAL_ASCII_TERMS = frozenset(
    {
        "AI",
        "AMD",
        "Anthropic",
        "Claude",
        "Claude Code",
        "Codex",
        "Cursor",
        "DeepSeek",
        "GPT",
        "Grok",
        "llama.cpp",
        "MCP",
        "NVLink",
        "Ollama",
        "OpenAI",
        "OpenRouter",
        "Qwen",
        "ROCm",
        "SpaceX",
        "vLLM",
        "Zebra",
    }
)

Transport = Callable[[dict[str, Any], float], dict[str, Any]]


class LLMPostprocessError(RuntimeError):
    """LLM 后处理失败，且继续使用不完整结果并不安全。"""


@dataclass(frozen=True)
class _Part:
    id: str
    turn_index: int
    start: int
    text: str
    speaker: str


def _is_punctuation_or_space(char: str) -> bool:
    return char.isspace() or unicodedata.category(char).startswith("P")


def _is_cjk_char(char: str) -> bool:
    return "\u3400" <= char <= "\u9fff"


def _text_without_punctuation_or_space(text: str) -> str:
    return "".join(char for char in text if not _is_punctuation_or_space(char))


def _keep_only_proposed_punctuation(source: str, proposed: str) -> str:
    """Keep model punctuation positions while restoring every source character."""
    source_characters = _text_without_punctuation_or_space(source)
    proposed_characters = _text_without_punctuation_or_space(proposed)
    boundary_map: dict[int, int] = {}
    if len(source_characters) == len(proposed_characters):
        boundary_map = {index: index for index in range(len(source_characters) + 1)}
    else:
        max_delta = max(2, min(8, round(len(source_characters) * 0.03)))
        matcher = SequenceMatcher(None, proposed_characters, source_characters, autojunk=False)
        if (
            abs(len(source_characters) - len(proposed_characters)) > max_delta
            or matcher.ratio() < 0.96
        ):
            raise LLMPostprocessError("模型大幅增删了非标点字符")
        for tag, p_start, p_end, s_start, s_end in matcher.get_opcodes():
            p_size = p_end - p_start
            s_size = s_end - s_start
            for boundary in range(p_start, p_end + 1):
                if tag == "equal":
                    mapped = s_start + (boundary - p_start)
                elif p_size == 0:
                    mapped = s_end
                else:
                    mapped = s_start + round(
                        (boundary - p_start) * s_size / p_size
                    )
                boundary_map[boundary] = mapped

    punctuation: dict[int, list[str]] = {}
    proposed_boundary = 0
    for char in proposed:
        if _is_punctuation_or_space(char):
            source_boundary = boundary_map.get(proposed_boundary)
            if source_boundary is not None:
                punctuation.setdefault(source_boundary, []).append(char)
        else:
            proposed_boundary += 1

    restored: list[str] = []
    for source_boundary in range(len(source_characters) + 1):
        restored.extend(punctuation.get(source_boundary, []))
        if source_boundary < len(source_characters):
            restored.append(source_characters[source_boundary])
    return "".join(restored)


class LLMPostprocessor:
    """可复用、可注入 transport 的 LLM 后处理器。"""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 45.0,
        max_retries: int = 2,
        chunk_chars: int = DEFAULT_CHUNK_CHARS,
        retry_backoff: float = 0.5,
        transport: Transport | None = None,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout 必须大于 0")
        if max_retries < 0:
            raise ValueError("max_retries 不能小于 0")
        if chunk_chars <= 0:
            raise ValueError("chunk_chars 必须大于 0")

        self.base_url = (
            base_url
            or os.environ.get("WHISPER_LLM_BASE_URL")
            or DEFAULT_BASE_URL
        ).rstrip("/")
        self.model = model or os.environ.get("WHISPER_LLM_MODEL") or DEFAULT_MODEL
        self.timeout = timeout
        self.max_retries = max_retries
        self.chunk_chars = chunk_chars
        self.retry_backoff = retry_backoff
        self._transport = transport or self._http_transport
        self._requests = 0
        self._retries = 0

    def process_turns(
        self, turns: Sequence[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """纠错并补标点，返回新 turns 和包含 corrections 的审计信息。"""
        copied = deepcopy(list(turns))
        self._validate_input(copied)
        self._requests = 0
        self._retries = 0

        if not copied:
            return copied, self._metadata([], 0, 0, 0)

        corrections: list[dict[str, Any]] = []
        correction_part_count = 0
        correction_rounds = 0
        correction_chunk_chars = min(
            self.chunk_chars * 3, MAX_CORRECTION_CHUNK_CHARS
        )
        # 第一轮找明显错误；如果确实改到了内容，再做一次 recall pass，专门补漏。
        # 两轮共享批量审计和上下文预算，避免退回旧版“每块单独审计”的开销。
        for correction_round in range(2):
            correction_parts = self._make_parts(copied)
            correction_part_count += len(correction_parts)
            correction_results: list[
                list[tuple[_Part, str, list[dict[str, Any]]]]
            ] = []
            candidates: list[tuple[_Part, dict[str, Any]]] = []
            for chunk_index, chunk in enumerate(
                self._pack_parts(correction_parts, limit=correction_chunk_chars)
            ):
                result = self._validated_request(
                    phase="correction",
                    chunk_index=chunk_index,
                    parts=chunk,
                    validator=lambda data, current=chunk: self._validate_corrections(
                        data, current
                    ),
                )
                correction_results.append(result)
                candidates.extend(
                    (part, patch)
                    for part, _text, patches in result
                    for patch in patches
                )

            approved = self._auto_approve_candidates(candidates)
            review_candidates = [
                (index, candidate)
                for index, candidate in enumerate(candidates)
                if index not in approved
            ]
            approved.update(self._review_corrections(review_candidates))

            corrected_parts: dict[str, str] = {}
            candidate_index = 0
            accepted_count = 0
            for result in correction_results:
                for part, _text, patches in result:
                    accepted = []
                    for patch in patches:
                        if candidate_index in approved:
                            accepted.append(patch)
                            accepted_count += 1
                            audit = dict(patch)
                            audit["turn_id"] = self._public_turn_id(
                                copied[part.turn_index], part.turn_index
                            )
                            audit["start"] += part.start
                            audit["end"] = audit["start"] + len(audit["from"])
                            audit["part_id"] = part.id
                            audit["round"] = correction_round + 1
                            corrections.append(audit)
                        candidate_index += 1
                    corrected_parts[part.id] = self._apply_patches(part.text, accepted)

            self._merge_parts(copied, correction_parts, corrected_parts)
            correction_rounds += 1
            if accepted_count == 0:
                break

        self._propagate_repeated_ascii_corrections(copied, corrections)

        punctuation_parts = self._make_parts(copied)
        punctuated_parts: dict[str, str] = {}
        for chunk_index, chunk in enumerate(
            self._pack_parts(
                punctuation_parts,
                limit=min(self.chunk_chars * 2, MAX_PUNCTUATION_CHUNK_CHARS),
            )
        ):
            result = self._validated_request(
                phase="punctuation",
                chunk_index=chunk_index,
                parts=chunk,
                validator=lambda data, current=chunk: self._validate_punctuation(
                    data, current
                ),
            )
            punctuated_parts.update(result)

        self._merge_parts(copied, punctuation_parts, punctuated_parts)
        return copied, self._metadata(
            corrections,
            correction_part_count,
            len(punctuation_parts),
            correction_rounds,
        )

    @staticmethod
    def _auto_approve_candidates(
        candidates: list[tuple[_Part, dict[str, Any]]]
    ) -> set[int]:
        """只跳过已知官方 ASCII 专名的审计；未知修改仍需二次确认。"""
        return {
            index
            for index, (_part, patch) in enumerate(candidates)
            if patch["from"].isascii()
            and patch["to"].isascii()
            and patch["to"] in OFFICIAL_ASCII_TERMS
            and SequenceMatcher(
                None,
                patch["from"].lower(),
                patch["to"].lower(),
                autojunk=False,
            ).ratio()
            >= 0.55
        }

    def _review_corrections(
        self,
        candidates: list[tuple[int, tuple[_Part, dict[str, Any]]]],
    ) -> set[int]:
        """批量审计高风险候选，只发送每条候选附近的上下文。"""
        if not candidates:
            return set()
        approved: set[int] = set()
        batches: list[list[tuple[int, tuple[_Part, dict[str, Any]]]]] = []
        current: list[tuple[int, tuple[_Part, dict[str, Any]]]] = []
        current_size = 0
        for item in candidates:
            index, (part, patch) = item
            start = patch["start"]
            context_start = max(0, start - 80)
            context_end = min(len(part.text), start + len(patch["from"]) + 80)
            context = part.text[context_start:context_end]
            item_size = len(context) + len(json.dumps(patch, ensure_ascii=False)) + 100
            if current and current_size + item_size > MAX_REVIEW_CANDIDATE_CHARS:
                batches.append(current)
                current = []
                current_size = 0
            current.append(item)
            current_size += item_size
        if current:
            batches.append(current)

        for batch_index, batch in enumerate(batches):
            public_candidates = []
            for index, (part, patch) in batch:
                start = patch["start"]
                context_start = max(0, start - 80)
                context_end = min(len(part.text), start + len(patch["from"]) + 80)
                public_candidates.append(
                    {
                        "index": index,
                        "id": part.id,
                        "context": part.text[context_start:context_end],
                        **patch,
                    }
                )
            approved.update(
                self._validated_request(
                    phase="review",
                    chunk_index=batch_index,
                    parts=[],
                    candidates=public_candidates,
                    validator=lambda data, values=tuple(
                        item[0] for item in batch
                    ): self._validate_review(data, values),
                )
            )
        return approved

    @staticmethod
    def _propagate_repeated_ascii_corrections(
        turns: list[dict[str, Any]], corrections: list[dict[str, Any]]
    ) -> None:
        """Propagate only proper-name-like corrections independently approved twice."""
        counts = Counter(
            (item["from"], item["to"])
            for item in corrections
            if item["from"].isascii() and item["to"].isascii()
        )
        confidence_by_pair: dict[tuple[str, str], float] = {}
        for item in corrections:
            pair = (item["from"], item["to"])
            confidence_by_pair[pair] = min(
                confidence_by_pair.get(pair, 1.0), float(item["confidence"])
            )

        for (source, target), count in counts.items():
            if (
                count < 2
                or len(source) < 4
                or target not in OFFICIAL_ASCII_TERMS
            ):
                continue
            pattern = re.compile(
                rf"(?<![A-Za-z0-9]){re.escape(source)}(?![A-Za-z0-9])"
            )
            for turn_index, turn in enumerate(turns):
                text = turn["text"]
                matches = list(pattern.finditer(text))
                if not matches:
                    continue
                turn["text"] = pattern.sub(target, text)
                offset = 0
                for match in matches:
                    start = match.start() + offset
                    corrections.append(
                        {
                            "turn_id": LLMPostprocessor._public_turn_id(
                                turn, turn_index
                            ),
                            "start": start,
                            "from": source,
                            "to": target,
                            "reason": f"同一专名已在 {count} 处通过独立审计",
                            "confidence": confidence_by_pair[(source, target)],
                            "end": start + len(source),
                            "part_id": None,
                            "round": "propagated",
                        }
                    )
                    offset += len(target) - len(source)

    def _metadata(
        self,
        corrections: list[dict[str, Any]],
        correction_parts: int,
        punctuation_parts: int,
        correction_rounds: int,
    ) -> dict[str, Any]:
        return {
            "corrections": corrections,
            "meta": {
                "base_url": self.base_url,
                "model": self.model,
                "chunk_chars": self.chunk_chars,
                "correction_chunk_chars": min(
                    self.chunk_chars * 3, MAX_CORRECTION_CHUNK_CHARS
                ),
                "punctuation_chunk_chars": min(
                    self.chunk_chars * 2, MAX_PUNCTUATION_CHUNK_CHARS
                ),
                "context_budget": MAX_CONTEXT_BUDGET,
                "correction_parts": correction_parts,
                "correction_rounds": correction_rounds,
                "punctuation_parts": punctuation_parts,
                "requests": self._requests,
                "retries": self._retries,
            },
        }

    @staticmethod
    def _validate_input(turns: list[dict[str, Any]]) -> None:
        for index, turn in enumerate(turns):
            if not isinstance(turn, dict):
                raise TypeError(f"turns[{index}] 必须是对象")
            if not isinstance(turn.get("text"), str):
                raise TypeError(f"turns[{index}].text 必须是字符串")

    @staticmethod
    def _public_turn_id(turn: dict[str, Any], index: int) -> str | int:
        if "id" in turn:
            return turn["id"]
        if "turn_id" in turn:
            return turn["turn_id"]
        return index

    def _make_parts(self, turns: list[dict[str, Any]]) -> list[_Part]:
        parts: list[_Part] = []
        for turn_index, turn in enumerate(turns):
            text = turn["text"]
            speaker = str(turn.get("speaker", ""))
            slices = self._split_text(text)
            for part_index, (start, value) in enumerate(slices):
                parts.append(
                    _Part(
                        id=f"t{turn_index}.p{part_index}",
                        turn_index=turn_index,
                        start=start,
                        text=value,
                        speaker=speaker,
                    )
                )
        return parts

    def _split_text(self, text: str) -> list[tuple[int, str]]:
        result: list[tuple[int, str]] = []
        start = 0
        while start < len(text):
            hard_end = min(
                start + min(self.chunk_chars, MAX_PUNCTUATION_CHUNK_CHARS),
                len(text),
            )
            end = hard_end
            if hard_end < len(text):
                search_start = max(start + 1, hard_end - min(80, self.chunk_chars // 4))
                for candidate in range(hard_end, search_start - 1, -1):
                    if _is_punctuation_or_space(text[candidate - 1]):
                        end = candidate
                        break
            result.append((start, text[start:end]))
            start = end
        return result

    def _pack_parts(
        self, parts: list[_Part], *, limit: int | None = None
    ) -> list[list[_Part]]:
        limit = limit or self.chunk_chars
        chunks: list[list[_Part]] = []
        current: list[_Part] = []
        current_chars = 0
        for part in parts:
            part_chars = len(part.text)
            if current and (
                current_chars + part_chars > limit
                or len(current) >= MAX_PARTS_PER_CHUNK
            ):
                chunks.append(current)
                current = []
                current_chars = 0
            current.append(part)
            current_chars += part_chars
        if current:
            chunks.append(current)
        return chunks

    @staticmethod
    def _merge_parts(
        turns: list[dict[str, Any]], parts: list[_Part], values: dict[str, str]
    ) -> None:
        grouped: list[list[str]] = [[] for _ in turns]
        for part in parts:
            if part.id not in values:
                raise LLMPostprocessError(f"缺少分片结果: {part.id}")
            grouped[part.turn_index].append(values[part.id])
        for index, text_parts in enumerate(grouped):
            turns[index]["text"] = "".join(text_parts)

    def _validated_request(
        self,
        *,
        phase: str,
        chunk_index: int,
        parts: list[_Part],
        validator: Callable[[dict[str, Any]], Any],
        candidates: list[dict[str, Any]] | None = None,
    ) -> Any:
        messages = self._messages(phase, parts, candidates)
        retry_messages = list(messages)
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            if attempt:
                self._retries += 1
                if self.retry_backoff:
                    time.sleep(self.retry_backoff * (2 ** (attempt - 1)))
            try:
                self._requests += 1
                payload = {
                    "model": self.model,
                    "messages": retry_messages,
                    "temperature": 0,
                    "max_tokens": (
                        1200
                        if phase == "correction"
                        else 700
                        if phase == "review"
                        else 1800
                    ),
                    "response_format": {"type": "json_object"},
                }
                # 不依赖 tokenizer 也要保守限制上下文：中文字符通常接近 token，
                # JSON 和 system prompt 也计入预算。超过预算直接报错，避免请求撞上 8000。
                request_size = sum(
                    len(message.get("content", "")) for message in retry_messages
                )
                if request_size + payload["max_tokens"] > MAX_CONTEXT_BUDGET:
                    raise LLMPostprocessError(
                        f"{phase} 请求超过保守上下文预算: "
                        f"{request_size}+{payload['max_tokens']}>{MAX_CONTEXT_BUDGET}"
                    )
                response = self._transport(payload, self.timeout)
                return validator(self._extract_json(response))
            except (LLMPostprocessError, OSError, ValueError, TypeError) as exc:
                last_error = exc
                if isinstance(exc, LLMPostprocessError):
                    retry_messages = [
                        *messages,
                        {
                            "role": "user",
                            "content": (
                                f"上一份响应被校验器拒绝：{exc}。"
                                "请严格修正结构或内容后，只重新输出约定的 JSON。"
                            ),
                        },
                    ]
        raise LLMPostprocessError(
            f"{phase} 第 {chunk_index + 1} 块在 "
            f"{self.max_retries + 1} 次尝试后失败: {last_error}"
        ) from last_error

    @staticmethod
    def _messages(
        phase: str,
        parts: list[_Part],
        candidates: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, str]]:
        units = [
            {"id": part.id, "speaker": part.speaker, "text": part.text}
            for part in parts
        ]
        if phase == "correction":
            system = (
                "你是中文 AI 技术播客的高召回 ASR 纠错编辑。speaker 和 id 是不可修改的硬边界，"
                "不要判断、合并或重分配说话人。只报告置信度至少 0.85 且有上下文依据的高概率"
                "听错、写错、拆错或粘连。逐个检查所有中文短词、英文 token 和中英文混合 token。"
                "允许非同音、近音、形近、错拼、大小写、空格和词边界错误；即使原词单独看成立，"
                "只要本句上下文明显更支持候选，也可以报告。"
                "本稿重点检查这些 AI 领域术语及其错写：Claude、Claude Code、Qwen、DeepSeek、"
                "Ollama、llama.cpp、vLLM、ROCm、Zebra、Cursor、OpenAI、Anthropic、Codex、"
                "OpenRouter、GPT、Grok、MCP、NVLink。不要只返回最显眼的一处。"
                "绝不根据世界常识补写原文没有的信息；数字、数量单位、日期、金额、版本号、"
                "硬件型号、点赞数和事实保持不变，未知缩写或专名不要擅自展开成已知词。"
                "不要润色、删口语、改写完整句子或把一种成立表达换成另一种成立表达。"
                "confidence 是必填的 0 到 1 数字。每块最多返回 16 个 patch，reason 最多 30 个字，"
                "只写直接依据，禁止输出推理过程。中文修改不要求同音或同拼音。严格只返回 JSON 对象："
                '{"patches":[{"turn_id":"t0.p0","start":0,"from":"错词",'
                '"to":"正词","reason":"简短原因","confidence":0.85}]}。'
                "from 和 to 必须不同，start 是该分片 text 中从 0 开始的字符偏移；无修改返回空 patches。"
            )
            user_content = {"turns": units}
        elif phase == "review":
            system = (
                "你是中文 ASR 纠错的最终审计员。逐条审查候选及其局部上下文；中文修改不要求"
                "同音或同拼音，但必须有明确的句内证据，不能只因为候选更顺或更符合常识就批准。"
                "原词在当前句中明显搭配不当、候选是固定术语或标准专名时可以批准；如果原词和"
                "候选都可能成立，拒绝。未知英文缩写或专名不要擅自替换成已知词，两个都是真实"
                "英文单词时不要互换。不得猜测或改变数字、日期、金额、数量、版本、硬件型号、"
                "点赞数和事实，不得补字、删字、润色或整句改写。只输出 JSON："
                '{"approved":[候选的 index 整数]}。不输出解释。'
            )
            user_content = {"candidates": candidates or []}
        else:
            system = (
                "你是中文 ASR 标点恢复器。speaker 和 id 是不可修改的硬边界，"
                "不要判断、合并或重分配说话人。只能增删标点和空白，不能增删替换任何其他字符。"
                "每个输入 id 必须且只能输出一次，顺序不变。严格只返回 JSON 对象："
                '{"turns":[{"id":"t0.p0","text":"补好标点的原文。"}]}。'
            )
            user_content = {"turns": units}
        return [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": json.dumps(user_content, ensure_ascii=False),
            },
        ]

    @staticmethod
    def _extract_json(response: dict[str, Any]) -> dict[str, Any]:
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMPostprocessError("API 响应缺少 choices[0].message.content") from exc
        if not isinstance(content, str):
            raise LLMPostprocessError("API 返回的 message.content 不是字符串")
        try:
            value = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMPostprocessError(f"模型未返回严格 JSON: {exc.msg}") from exc
        if not isinstance(value, dict):
            raise LLMPostprocessError("模型 JSON 顶层必须是对象")
        return value

    @staticmethod
    def _validate_corrections(
        data: dict[str, Any], parts: list[_Part]
    ) -> list[tuple[_Part, str, list[dict[str, Any]]]]:
        if set(data) != {"patches"} or not isinstance(data["patches"], list):
            raise LLMPostprocessError("纠错响应必须且只能包含 patches 数组")
        if len(data["patches"]) > 16:
            raise LLMPostprocessError("单块 correction patch 不能超过 16 个")
        by_id = {part.id: part for part in parts}
        patches_by_id: dict[str, list[dict[str, Any]]] = {
            part.id: [] for part in parts
        }
        required = {"turn_id", "start", "from", "to", "reason", "confidence"}
        for index, patch in enumerate(data["patches"]):
            if not isinstance(patch, dict) or set(patch) != required:
                raise LLMPostprocessError(f"patches[{index}] 字段不符合约定")
            part_id = patch["turn_id"]
            if part_id not in by_id:
                raise LLMPostprocessError(f"patches[{index}] 引用了未知 turn_id")
            start = patch["start"]
            source = patch["from"]
            target = patch["to"]
            confidence = patch["confidence"]
            if isinstance(start, bool) or not isinstance(start, int) or start < 0:
                raise LLMPostprocessError(f"patches[{index}].start 必须是非负整数")
            if not isinstance(source, str) or not source:
                raise LLMPostprocessError(f"patches[{index}].from 必须是非空字符串")
            if not isinstance(target, str) or not target:
                raise LLMPostprocessError(f"patches[{index}].to 必须是非空字符串")
            if not isinstance(patch["reason"], str) or not patch["reason"]:
                raise LLMPostprocessError(f"patches[{index}].reason 必须是非空字符串")
            if (
                isinstance(confidence, bool)
                or not isinstance(confidence, (int, float))
                or not 0 <= confidence <= 1
            ):
                raise LLMPostprocessError(f"patches[{index}].confidence 必须在 0 到 1 之间")
            part = by_id[part_id]
            if part.text[start : start + len(source)] != source:
                occurrences = [
                    match.start() for match in re.finditer(re.escape(source), part.text)
                ]
                if len(occurrences) != 1:
                    continue
                start = occurrences[0]
            if (
                target == source
                or confidence < MIN_CORRECTION_CONFIDENCE
                or len(patch["reason"]) > 40
                or re.findall(r"\d+", source) != re.findall(r"\d+", target)
                or (
                    len(source) == len(target) == 1
                    and _is_cjk_char(source)
                    and _is_cjk_char(target)
                )
            ):
                continue
            normalized_patch = dict(patch)
            normalized_patch["start"] = start
            patches_by_id[part_id].append(normalized_patch)

        result: list[tuple[_Part, str, list[dict[str, Any]]]] = []
        for part in parts:
            patches = sorted(patches_by_id[part.id], key=lambda item: item["start"])
            previous_end = -1
            non_overlapping: list[dict[str, Any]] = []
            for patch in patches:
                if patch["start"] < previous_end:
                    continue
                previous_end = patch["start"] + len(patch["from"])
                non_overlapping.append(patch)
            text = LLMPostprocessor._apply_patches(part.text, non_overlapping)
            result.append((part, text, non_overlapping))
        return result

    @staticmethod
    def _apply_patches(text: str, patches: list[dict[str, Any]]) -> str:
        for patch in reversed(sorted(patches, key=lambda item: item["start"])):
            start = patch["start"]
            text = text[:start] + patch["to"] + text[start + len(patch["from"]) :]
        return text

    @staticmethod
    def _validate_review(
        data: dict[str, Any], candidate_indices: Sequence[int]
    ) -> set[int]:
        if set(data) != {"approved"} or not isinstance(data["approved"], list):
            raise LLMPostprocessError("纠错审计响应必须且只能包含 approved 数组")
        allowed = set(candidate_indices)
        approved: set[int] = set()
        for index in data["approved"]:
            if (
                isinstance(index, bool)
                or not isinstance(index, int)
                or index not in allowed
            ):
                raise LLMPostprocessError("approved 包含无效候选序号")
            if index in approved:
                raise LLMPostprocessError("approved 包含重复候选序号")
            approved.add(index)
        return approved

    @staticmethod
    def _validate_punctuation(
        data: dict[str, Any], parts: list[_Part]
    ) -> dict[str, str]:
        if set(data) != {"turns"} or not isinstance(data["turns"], list):
            raise LLMPostprocessError("标点响应必须且只能包含 turns 数组")
        if len(data["turns"]) != len(parts):
            raise LLMPostprocessError("标点响应的 turn 数量与输入不一致")
        output: dict[str, str] = {}
        for index, (item, part) in enumerate(zip(data["turns"], parts, strict=True)):
            if not isinstance(item, dict) or set(item) != {"id", "text"}:
                raise LLMPostprocessError(f"turns[{index}] 字段不符合约定")
            if item["id"] != part.id:
                raise LLMPostprocessError(f"turns[{index}].id 或顺序被修改")
            if not isinstance(item["text"], str):
                raise LLMPostprocessError(f"turns[{index}].text 必须是字符串")
            try:
                output[part.id] = _keep_only_proposed_punctuation(
                    part.text, item["text"]
                )
            except LLMPostprocessError as exc:
                raise LLMPostprocessError(f"turns[{index}] {exc}") from exc
        return output

    def _http_transport(
        self, payload: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        api_key = os.environ.get("WHISPER_LLM_API_KEY") or os.environ.get(
            "OPENAI_API_KEY"
        )
        if not api_key:
            raise LLMPostprocessError(
                "缺少 API key；请设置 WHISPER_LLM_API_KEY 或 OPENAI_API_KEY"
            )
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read(512).decode("utf-8", errors="replace")
            raise LLMPostprocessError(f"LLM API HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise LLMPostprocessError(f"LLM API 连接失败: {exc.reason}") from exc
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LLMPostprocessError("LLM API 返回了无效 JSON") from exc
        if not isinstance(value, dict):
            raise LLMPostprocessError("LLM API 响应顶层不是对象")
        return value


def process_turns(
    turns: Sequence[dict[str, Any]], **options: Any
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """便捷入口；认证信息仅从环境变量读取。"""
    return LLMPostprocessor(**options).process_turns(turns)
