import os
from dotenv import load_dotenv

load_dotenv()

MIMO_API_KEY = os.getenv("MIMO_API_KEY")
MIMO_BASE_URL = os.getenv("MIMO_BASE_URL", "https://token-plan-cn.xiaomimimo.com/v1")
MIMO_ASR_MODEL = "mimo-v2.5-asr"

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")

STT_MAX_WORKERS = max(1, int(os.getenv("STT_MAX_WORKERS", "4")))
STT_REQUESTS_PER_MINUTE = max(0, int(os.getenv("STT_REQUESTS_PER_MINUTE", "90")))
STT_RATE_LIMIT_RETRIES = max(0, int(os.getenv("STT_RATE_LIMIT_RETRIES", "2")))

AUTH_SECRET = os.getenv("AUTH_SECRET") or None
