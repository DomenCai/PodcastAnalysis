from __future__ import annotations

import json

import pytest

from server.llm_postprocessor import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    LLMPostprocessError,
    LLMPostprocessor,
    process_turns,
)


def _response(value: dict) -> dict:
    return {"choices": [{"message": {"content": json.dumps(value, ensure_ascii=False)}}]}


def _echo_transport(payload: dict, _timeout: float) -> dict:
    request = json.loads(payload["messages"][1]["content"])
    if "ASR 纠错编辑" in payload["messages"][0]["content"]:
        patches = []
        for turn in request["turns"]:
            start = turn["text"].find("创业版")
            if start >= 0:
                patches.append(
                    {
                        "turn_id": turn["id"],
                        "start": start,
                        "from": "创业版",
                        "to": "创业板",
                        "reason": "证券板块名称",
                        "confidence": 0.99,
                    }
                )
        return _response({"patches": patches})
    if "最终审计员" in payload["messages"][0]["content"]:
        return _response(
            {"approved": [item["index"] for item in request["candidates"]]}
        )
    return _response(
        {
            "turns": [
                {"id": turn["id"], "text": turn["text"] + "。"}
                for turn in request["turns"]
            ]
        }
    )


def test_processes_corrections_then_punctuation_without_changing_speaker():
    turns = [
        {"id": "turn-1", "speaker": "SPEAKER_01", "start": 0.0, "text": "创业版上涨"},
        {"id": "turn-2", "speaker": "SPEAKER_00", "start": 3.2, "text": "确实如此"},
    ]

    processed, audit = process_turns(
        turns, transport=_echo_transport, retry_backoff=0
    )

    assert [turn["text"] for turn in processed] == ["创业板上涨。", "确实如此。"]
    assert processed[0]["speaker"] == "SPEAKER_01"
    assert processed[0]["start"] == 0.0
    assert turns[0]["text"] == "创业版上涨"  # 不原地修改调用方数据
    assert audit["corrections"] == [
        {
            "turn_id": "turn-1",
            "start": 0,
            "from": "创业版",
            "to": "创业板",
            "reason": "证券板块名称",
            "confidence": 0.99,
            "end": 3,
            "part_id": "t0.p0",
            "round": 1,
        }
    ]
    assert audit["meta"]["model"] == DEFAULT_MODEL
    assert audit["meta"]["base_url"] == DEFAULT_BASE_URL
    assert audit["meta"]["requests"] == 4
    assert audit["meta"]["correction_rounds"] == 2


def test_splits_long_turn_and_merges_it_back():
    seen_sizes: list[tuple[str, int]] = []

    def transport(payload: dict, timeout: float) -> dict:
        request = json.loads(payload["messages"][1]["content"])
        assert (
            sum(len(message["content"]) for message in payload["messages"])
            + payload["max_tokens"]
            < 8000
        )
        phase = (
            "correction"
            if "ASR 纠错编辑" in payload["messages"][0]["content"]
            else "punctuation"
        )
        seen_sizes.append(
            (phase, sum(len(turn["text"]) for turn in request["turns"]))
        )
        return _echo_transport(payload, timeout)

    original = "这是一段没有标点的转写文本" * 8
    processed, audit = process_turns(
        [{"speaker": "A", "text": original}],
        transport=transport,
        chunk_chars=30,
        retry_backoff=0,
    )

    assert all(
        size <= (90 if phase == "correction" else 60)
        for phase, size in seen_sizes
    )
    assert processed[0]["speaker"] == "A"
    assert processed[0]["text"].replace("。", "") == original
    assert audit["meta"]["correction_parts"] > 1
    assert audit["meta"]["punctuation_parts"] > 1


def test_retries_invalid_json_and_then_succeeds():
    calls = 0

    def transport(payload: dict, timeout: float) -> dict:
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"choices": [{"message": {"content": "```json\n{}\n```"}}]}
        return _echo_transport(payload, timeout)

    processed, audit = process_turns(
        [{"speaker": "A", "text": "你好"}],
        transport=transport,
        retry_backoff=0,
    )

    assert processed[0]["text"] == "你好。"
    assert audit["meta"]["retries"] == 1
    assert calls == 3  # 纠错重试一次，标点一次


def test_skips_correction_when_wrong_offset_cannot_be_uniquely_recovered():
    def transport(payload: dict, _timeout: float) -> dict:
        request = json.loads(payload["messages"][1]["content"])
        turn = request["turns"][0]
        if "ASR 纠错编辑" not in payload["messages"][0]["content"]:
            return _response(
                {"turns": [{"id": turn["id"], "text": turn["text"] + "。"}]}
            )
        return _response(
            {
                "patches": [
                    {
                        "turn_id": turn["id"],
                        "start": 1,
                        "from": "错字",
                        "to": "正确",
                        "reason": "测试",
                        "confidence": 1,
                    }
                ]
            }
        )

    processed, audit = process_turns(
        [{"speaker": "A", "text": "错字错字"}],
        transport=transport,
        max_retries=0,
        retry_backoff=0,
    )

    assert processed[0]["text"] == "错字错字。"
    assert audit["corrections"] == []


def test_punctuation_response_cannot_rewrite_same_length_words():
    def transport(payload: dict, _timeout: float) -> dict:
        request = json.loads(payload["messages"][1]["content"])
        if "ASR 纠错编辑" in payload["messages"][0]["content"]:
            return _response({"patches": []})
        return _response(
            {"turns": [{"id": request["turns"][0]["id"], "text": "您好。"}]}
        )
    processed, _audit = process_turns(
        [{"speaker": "A", "text": "你好"}],
        transport=transport,
        max_retries=1,
        retry_backoff=0,
    )

    assert processed[0]["text"] == "你好。"


def test_rejects_punctuation_response_that_adds_words():
    def transport(payload: dict, _timeout: float) -> dict:
        request = json.loads(payload["messages"][1]["content"])
        if "ASR 纠错编辑" in payload["messages"][0]["content"]:
            return _response({"patches": []})
        return _response(
            {"turns": [{"id": request["turns"][0]["id"], "text": "你们好。"}]}
        )
    with pytest.raises(LLMPostprocessError, match="增删了非标点字符"):
        process_turns(
            [{"speaker": "A", "text": "你好"}],
            transport=transport,
            max_retries=0,
            retry_backoff=0,
        )


def test_default_transport_requires_key_from_environment(monkeypatch):
    monkeypatch.delenv("WHISPER_LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    processor = LLMPostprocessor(max_retries=0, retry_backoff=0)

    with pytest.raises(LLMPostprocessError, match="WHISPER_LLM_API_KEY"):
        processor.process_turns([{"speaker": "A", "text": "你好"}])


def test_empty_input_does_not_call_api():
    def unexpected(_payload: dict, _timeout: float) -> dict:
        raise AssertionError("不应调用 API")

    processed, audit = process_turns([], transport=unexpected)
    assert processed == []
    assert audit["corrections"] == []
    assert audit["meta"]["requests"] == 0


def test_empty_turn_is_preserved_without_sending_punctuation_only_text():
    def unexpected(_payload: dict, _timeout: float) -> dict:
        raise AssertionError("不应调用 API")

    turns = [{"id": "empty", "speaker": "A", "text": ""}]
    processed, audit = process_turns(turns, transport=unexpected)

    assert processed == turns
    assert audit["meta"]["requests"] == 0


def test_non_phonetic_chinese_correction_can_be_approved_by_review():
    def transport(payload: dict, _timeout: float) -> dict:
        request = json.loads(payload["messages"][1]["content"])
        if "ASR 纠错编辑" in payload["messages"][0]["content"]:
            return _response(
                {
                    "patches": [
                        {
                            "turn_id": request["turns"][0]["id"],
                            "start": 0,
                            "from": "实在",
                            "to": "实锤",
                            "reason": "上下文明确指已被证实",
                            "confidence": 0.99,
                        }
                    ]
                }
            )
        if "最终审计员" in payload["messages"][0]["content"]:
            return _response({"approved": [request["candidates"][0]["index"]]})
        return _response(
            {
                "turns": [
                    {"id": turn["id"], "text": turn["text"]}
                    for turn in request["turns"]
                ]
            }
        )

    processed, audit = process_turns(
        [{"speaker": "A", "text": "这个消息已经实在了"}],
        transport=transport,
        max_retries=0,
        retry_backoff=0,
    )

    assert processed[0]["text"] == "这个消息已经实锤了"
    assert audit["corrections"][0]["from"] == "实在"


def test_repeated_ascii_proper_name_correction_is_propagated():
    turns = [
        {"id": "one", "text": "Claude"},
        {"id": "two", "text": "Claude"},
        {"id": "three", "text": "Cloud Opus"},
    ]
    corrections = [
        {"from": "Cloud", "to": "Claude", "confidence": 0.99},
        {"from": "Cloud", "to": "Claude", "confidence": 0.98},
    ]

    LLMPostprocessor._propagate_repeated_ascii_corrections(turns, corrections)

    assert turns[2]["text"] == "Claude Opus"
    assert corrections[-1]["round"] == "propagated"
    assert corrections[-1]["turn_id"] == "three"
