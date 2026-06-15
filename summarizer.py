from openai import OpenAI

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL

SYSTEM_PROMPT = """你是一位资深播客内容分析师。你的工作是从播客逐字稿中提取高密度信息，生成一份让读者即使不听原节目也能获得核心价值的结构化笔记。

分析原则：
- 忠实于原始内容，不编造逐字稿中没有的信息
- 区分事实陈述与个人观点
- 保留具体的数字、案例和证据——这些往往是最有价值的部分
- 口语化表述中的精彩观点，用更精练的语言重新表达
- 按照节目实际的话题脉络组织输出，不要强行套模板"""

SUMMARY_PROMPT = """请基于以下播客逐字稿生成一份结构化内容笔记。

{meta_section}
## 输出要求

### 节目概述
用 2-3 句话概括本期核心内容和价值。点明节目类型（对谈/独白/书评等）和主要话题。

### 内容脉络
按照节目的话题推进顺序，分段整理（通常 3-6 段）。每段包括：
- **段落标题**（自行提炼，简洁有力）
- **关键要点**：该段落最重要的信息，用要点列表呈现
- **值得记录的细节**：具体数字、案例、工具/产品名、方法论等

### 核心洞察
提炼 3-5 个全篇最有价值的认知或结论。优先选择：
- 反直觉的发现或观点
- 有数据/案例支撑的结论
- 可迁移到其他场景的方法论或思维方式

### 提及的资源
列出内容中提到的工具、书籍、产品、网站、人物等（如果有的话）。没有则省略此节。

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
