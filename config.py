import os
from dotenv import load_dotenv

load_dotenv()

MIMO_API_KEY = os.getenv("MIMO_API_KEY")
MIMO_BASE_URL = "https://api.xiaomimimo.com/v1"
MIMO_ASR_MODEL = "mimo-v2.5-asr"

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
