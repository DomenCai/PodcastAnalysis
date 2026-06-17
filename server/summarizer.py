from json_repair import repair_json
from openai import OpenAI

from server.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL

SYSTEM_PROMPT = """你是一个播客内容分析助手，服务对象每天有大量 1 小时左右的播客要过，没时间全听。你的任务是让他不听原片也能搞清楚：这期讲了什么、值不值得深入，值得的还能直接拿走精华。

原则：
- 忠实于内容，不编造逐字稿里没有的东西；区分事实陈述与个人观点。
- 保留说话人的保留意见、反例和犹豫——不要把所有内容都拔高成正面结论，原节目有多克制就还原多克制。
- 具体优先：具体的数字、案例、反直觉的发现是最值钱的，优先留住它们，而不是概括成正确却空洞的结论。
- 不硬套模板，按这期实际的价值类型（概念／事件／方法论／书评等）来组织和抽取。
- 逐字稿没有说话人标签，身份不确定时不要硬编（尤其别把主播说成嘉宾）；明显的转写错误（如 Cloud 实为 Claude、走样的品牌名）按常识理解。
- 只输出 JSON，不要任何额外文字、不要 Markdown 代码块包裹。字符串值内若要引用，请用中文引号「」或“”，不要用半角双引号，以免破坏 JSON。"""

SUMMARY_PROMPT = """请基于以下播客逐字稿，生成一份帮我快速搞懂这期内容的笔记，并以 JSON 输出。

{meta_section}## 输出 JSON 结构

{{
  "overview": [
    {{ "time": "MM:SS", "title": "本段小标题，没有则填 null", "text": "段落正文" }}
  ],
  "mindmap": {{
    "note": "若本期基本是闲聊、没什么可迁移的干货，用一句话说明（如“本期偏闲聊，干货不多，可听可不听”），此时 nodes 为空数组；有干货时 note 填 null",
    "nodes": [
      {{ "text": "要点", "tag": "价值类型或 null", "children": [] }}
    ]
  }},
  "worth_following": [
    {{ "type": "书|论文|工具|人物|播客|视频|其他", "title": "名称", "by": "作者/创作者，没有则 null", "note": "为什么值得追的一句话" }}
  ]
}}

## 各字段要求

### overview（这期讲了什么）—— 永远要有
按节目实际推进的顺序，梳理成一条清晰的时间线，让我 5 分钟读完就知道整期来龙去脉。总量约 1000 字，切成若干段（数组每个元素是一段）。
- time：该段起始的粗略时间戳，取自逐字稿，统一用 MM:SS（超过 1 小时用 HH:MM:SS）的单点，不要写区间。
- title：若该段有一个明确的小主题（如“商业科技快讯四则”），填进 title；否则填 null。
- text：压缩后的叙事主干，不要逐句复述；但具体案例、数字、关键转折必须留住。可用少量 Markdown（**加粗**、有序列表）。

### mindmap（思维导图）—— 提炼，可迁移的干货
按逻辑（不按时间）重新组织成一棵树：顶层节点是核心议题，往下挂子论点，再往下挂证据或例子。
- 顶层节点本身就代表“核心议题”，不要再给它打 tag。
- tag 只用来标注干货的价值类型，且只能取以下之一：概念、方法、反直觉、案例、事件、人物、书；不属于这些就填 null，不要自创或组合。
- children 为空时填空数组 []。
- 这一节是提炼，不要重复 overview 的时间线。若本期没什么干货，按上面 note 的说明处理。

### worth_following（值得追的）—— 真正值得读或尝试的
列出真正值得去读或尝试的书、论文、工具、人物、播客、视频。顺口提到的产品名不用列。没有就给空数组 []。

逐字稿：
{transcript}"""

# mindmap 节点 tag 与中文展示前缀无需后端处理，前端按 tag 渲染


def _build_meta_section(meta: dict | None) -> str:
    if not meta:
        return ""
    parts = ["## 节目信息"]
    if title := meta.get("title"):
        parts.append(f"- 标题：{title}")
    if podcast := meta.get("podcast_title"):
        parts.append(f"- 播客：{podcast}")
    if duration := meta.get("duration"):
        minutes = duration // 60
        parts.append(f"- 时长：约 {minutes} 分钟")
    if desc := meta.get("description"):
        # 截取描述前 1000 字作为参考，避免 token 浪费
        short_desc = desc[:1000] + ("..." if len(desc) > 1000 else "")
        parts.append(f"- 节目简介：{short_desc}")
    return "\n".join(parts) + "\n\n"


def summarize_transcript(
    transcript: str,
    meta: dict | None = None,
    api_key: str | None = None,
    base_url: str = LLM_BASE_URL,
    model: str = LLM_MODEL,
) -> dict:
    api_key = api_key or LLM_API_KEY
    if not api_key:
        raise ValueError("缺少 LLM_API_KEY")

    meta_section = _build_meta_section(meta)
    user_content = SUMMARY_PROMPT.format(
        meta_section=meta_section, transcript=transcript
    )

    client = OpenAI(api_key=api_key, base_url=base_url)
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.3,
        response_format={"type": "json_object"},
    )
    return _parse_summary(completion)


def _parse_summary(completion) -> dict:
    """从模型返回里提取 JSON：Claude 等常把 JSON 包在 ```json 围栏、前置一句话，
    或在中文文本里误用半角引号截断字符串；用 json_repair 兜住这些常见破损。"""
    choice = completion.choices[0]
    content = (choice.message.content or "").strip()
    if not content:
        raise ValueError(f"模型返回为空（finish_reason={choice.finish_reason}）")
    data = repair_json(content, return_objects=True)
    if not isinstance(data, dict):
        raise ValueError(
            f"模型未返回 JSON 对象（finish_reason={choice.finish_reason}）："
            f"{content[:300]!r}"
        )
    return data


def _nodes_to_markdown(nodes: list[dict], depth: int = 0) -> list[str]:
    lines: list[str] = []
    indent = "  " * depth
    for node in nodes:
        tag = node.get("tag")
        suffix = f" 【{tag}】" if tag else ""
        lines.append(f"{indent}- {node['text']}{suffix}")
        children = node.get("children") or []
        lines.extend(_nodes_to_markdown(children, depth + 1))
    return lines


def summary_to_markdown(data: dict) -> str:
    """把结构化摘要拼成可下载的 Markdown（导出用，前端渲染走结构化 JSON）。"""
    parts: list[str] = ["## 这期讲了什么", ""]
    for seg in data.get("overview", []):
        head = f"**[{seg['time']}]"
        head += f" {seg['title']}**" if seg.get("title") else "**"
        parts.append(head)
        parts.append("")
        parts.append(seg["text"])
        parts.append("")

    mindmap = data.get("mindmap") or {}
    parts.append("## 思维导图")
    parts.append("")
    if mindmap.get("note"):
        parts.append(mindmap["note"])
        parts.append("")
    else:
        parts.extend(_nodes_to_markdown(mindmap.get("nodes", [])))
        parts.append("")

    worth = data.get("worth_following") or []
    if worth:
        parts.append("## 值得追的")
        parts.append("")
        for item in worth:
            by = f"（{item['by']}）" if item.get("by") else ""
            note = f" — {item['note']}" if item.get("note") else ""
            parts.append(f"- **{item['title']}**{by}{note}")
        parts.append("")

    return "\n".join(parts).strip() + "\n"
