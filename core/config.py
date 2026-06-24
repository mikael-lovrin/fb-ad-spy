# -*- coding: utf-8 -*-
"""
Central configuration — loaded from environment variables / .env file.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")

# -- Facebook Ad Library -------------------------------------------------------
FB_ACCESS_TOKEN: str  = os.getenv("FB_ACCESS_TOKEN", "")
FB_AD_ACCOUNT_ID: str = os.getenv("FB_AD_ACCOUNT_ID", "")

# -- Anthropic Claude ----------------------------------------------------------
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL: str      = "claude-sonnet-4-6"

# -- OpenAI / Whisper ----------------------------------------------------------
OPENAI_API_KEY: str    = os.getenv("OPENAI_API_KEY", "")
USE_LOCAL_WHISPER: bool = os.getenv("USE_LOCAL_WHISPER", "true").lower() == "true"
WHISPER_MODEL_SIZE: str = os.getenv("WHISPER_MODEL_SIZE", "small")

# -- Database ------------------------------------------------------------------
# If DATABASE_URL is set → PostgreSQL (Supabase)
# Otherwise            → SQLite (local dev, file at data/ads.db)
DATABASE_URL: str = os.getenv("DATABASE_URL", "")
DB_PATH: str      = str(_ROOT / "data" / "ads.db")

# -- Storage -------------------------------------------------------------------
DEFAULT_COUNTRY: str  = os.getenv("DEFAULT_COUNTRY", "US")
DEFAULT_COUNT: int    = int(os.getenv("DEFAULT_COUNT", "50"))
MIN_ADS_FOR_SWIPE: int = int(os.getenv("MIN_ADS_FOR_SWIPE", "10"))

# -- Temp files (local only) ---------------------------------------------------
TEMP_DIR = _ROOT / "data" / "tmp"
TEMP_DIR.mkdir(parents=True, exist_ok=True)
