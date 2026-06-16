from openai import OpenAI

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL

SYSTEM_PROMPT = """你是一个播客内容分析助手，服务对象每天有大量 1 小时左右的播客要过，没时间全听。你的任务是让他不听原片也能搞清楚：这期讲了什么、值不值得深入，值得的还能直接拿走精华。

原则：
- 忠实于内容，不编造逐字稿里没有的东西；区分事实陈述与个人观点。
- 保留说话人的保留意见、反例和犹豫——不要把所有内容都拔高成正面结论，原节目有多克制就还原多克制。
- 具体优先：具体的数字、案例、反直觉的发现是最值钱的，优先留住它们，而不是概括成正确却空洞的结论。
- 不硬套模板，按这期实际的价值类型（概念／事件／方法论／书评等）来组织和抽取。
- 逐字稿没有说话人标签，身份不确定时不要硬编（尤其别把主播说成嘉宾）；明显的转写错误（如 Cloud 实为 Claude、走样的品牌名）按常识理解。
- 直接输出正文，不要“好的，这是……”之类的开场白。"""

SUMMARY_PROMPT = """请基于以下播客逐字稿，生成一份帮我快速搞懂这期内容的笔记。

{meta_section}## 输出结构

### 这期讲了什么
按节目实际推进的顺序，梳理出一条清晰的时间线，让我 5 分钟读完就知道整期的来龙去脉。约 1000 字，分成若干段，每段以粗略时间戳开头（如 [12:30]，取自逐字稿）。这是压缩后的叙事主干，不要逐句复述；但具体的案例、数字、关键转折必须留住。这一节永远要有。

### 思维导图
仅当这期有值得学习、可迁移的干货时才输出。用 Markdown 大纲，按逻辑（不按时间）重新组织：核心议题作为顶层，往下是子论点，再往下挂证据或例子。给每个要点标上价值类型，如【概念】【方法】【反直觉】【书】。这一节是提炼，不要重复上面的时间线。如果这期基本是闲聊、没什么可迁移的干货，就用一句话说明（例如“本期偏闲聊，干货不多，可听可不听”），并省略大纲。

### 值得追的
列出真正值得我去读或尝试的书、工具、论文、人物。顺口提到的产品名不用列。如果没有，整节省略。

---

逐字稿：
{transcript}"""


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
) -> str:
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
    )
    return completion.choices[0].message.content
