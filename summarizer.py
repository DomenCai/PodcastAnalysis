from openai import OpenAI

from config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL

SUMMARY_PROMPT = """请根据以下播客逐字稿，生成一份结构化摘要，包括：

1. **核心主题**：一句话概括本期播客讨论的核心内容
2. **关键观点**：列出 3-5 个最重要的观点或结论
3. **精彩金句**：摘录 2-3 句最有价值的原话
4. **行动建议**：如果有的话，列出可执行的建议

逐字稿内容：
{transcript}
"""

SYSTEM_PROMPT = "你是一个专业的播客内容分析师，擅长提取关键信息并生成结构化摘要。"


def summarize_transcript(
    transcript: str,
    api_key: str | None = None,
    base_url: str = LLM_BASE_URL,
    model: str = LLM_MODEL,
) -> str:
    api_key = api_key or LLM_API_KEY
    if not api_key:
        raise ValueError("缺少 LLM_API_KEY")

    client = OpenAI(api_key=api_key, base_url=base_url)
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": SUMMARY_PROMPT.format(transcript=transcript)},
        ],
        temperature=0.3,
    )
    return completion.choices[0].message.content
