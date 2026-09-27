from server.transcript_output import add_speaker_labels, build_formatted_text


def test_add_speaker_labels_uses_first_appearance_without_mutating_input():
    turns = [
        {"speaker": "SPEAKER_07", "start": 0, "text": "开场"},
        {"speaker": "SPEAKER_02", "start": 5, "text": "你好"},
        {"speaker": "SPEAKER_07", "start": 8, "text": "继续"},
    ]

    result = add_speaker_labels(turns)

    assert [turn["speaker_label"] for turn in result] == [
        "发言人 1",
        "发言人 2",
        "发言人 1",
    ]
    assert all("speaker_label" not in turn for turn in turns)
    assert result is not turns


def test_build_formatted_text_formats_speaker_turns():
    turns = [
        {"speaker": "host", "start": 0.9, "text": "大家好。"},
        {"speaker": "guest", "start": 5.8, "text": "你好！"},
    ]

    assert build_formatted_text(turns) == (
        "[00:00:00 发言人 1] 大家好。\n[00:00:05 发言人 2] 你好！"
    )


def test_build_formatted_text_supports_long_audio_and_safe_timestamp_fallbacks():
    turns = [
        {"speaker": "a", "start": 25 * 3600 + 61, "text": "超过一天"},
        {"speaker": "a", "start": -2, "text": "负时间"},
        {"speaker": "b", "text": "缺失时间"},
        {"speaker": "b", "start": "invalid", "text": "无效时间"},
    ]

    assert build_formatted_text(turns).splitlines() == [
        "[25:01:01 发言人 1] 超过一天",
        "[00:00:00 发言人 1] 负时间",
        "[00:00:00 发言人 2] 缺失时间",
        "[00:00:00 发言人 2] 无效时间",
    ]


def test_build_formatted_text_skips_empty_text_and_keeps_one_line_per_turn():
    turns = [
        {"speaker": "silent", "start": 0, "text": "  \n  "},
        {"speaker": "speaker", "start": 2, "text": "第一行\n第二行"},
        {"speaker": "speaker", "start": 3, "text": None},
    ]

    # Speaker numbering is derived from every input turn, including empty turns.
    assert build_formatted_text(turns) == "[00:00:02 发言人 2] 第一行 第二行"


def test_single_speaker_omits_speaker_label():
    turns = [
        {
            "speaker": "SPEAKER_00",
            "speaker_name": "发言人 1",
            "start": 0,
            "text": "第一段",
        },
        {
            "speaker": "SPEAKER_00",
            "speaker_label": "发言人 1",
            "start": 1,
            "text": "第二段",
        },
    ]

    labelled = add_speaker_labels(turns)
    assert all("speaker_label" not in turn for turn in labelled)
    assert all("speaker_name" not in turn for turn in labelled)
    assert build_formatted_text(turns) == ("[00:00:00] 第一段\n[00:00:01] 第二段")


def test_missing_speaker_is_treated_as_one_speaker_without_label():
    turns = [
        {"start": 0, "text": "未知一"},
        {"speaker": None, "start": 1, "text": "未知二"},
    ]

    assert build_formatted_text(turns) == ("[00:00:00] 未知一\n[00:00:01] 未知二")


def test_mimo_overlap_does_not_invent_a_third_speaker():
    turns = [
        {"start": 0, "text": "重叠发言", "overlapping_speech": True},
        {"start": 1, "text": "主播", "speaker": "host"},
        {"start": 2, "text": "嘉宾", "speaker": "guest"},
        {"start": 3, "text": "无法归属", "speaker": None},
    ]
    assert build_formatted_text(turns).splitlines() == [
        "[00:00:00 未知发言人] 重叠发言",
        "[00:00:01 发言人 1] 主播",
        "[00:00:02 发言人 2] 嘉宾",
        "[00:00:03 未知发言人] 无法归属",
    ]
