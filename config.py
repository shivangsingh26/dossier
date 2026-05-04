"""
config.py — Singleton config loader for the Dossier project.

Loads all environment variables from .env exactly once.
Every other module imports Config from here — no module ever calls load_dotenv() itself.

SINGLETON PATTERN EXPLAINED:
A singleton means only ONE instance of this class ever exists in the program's lifetime.
- First time you call Config(): it reads .env and stores all values as attributes
- Every time after that: you get back the same already-loaded object, nothing is re-read
- Why this matters:
    1. .env is read once — not on every import
    2. All agents see the exact same config values with zero risk of inconsistency
    3. If a required key is missing, you get ONE clear error at startup, not buried later
"""

import os
from pathlib import Path
from dotenv import load_dotenv


class Config:
    _instance = None  # Stores the one shared instance across the entire program

    def __new__(cls):
        # __new__ is called before __init__ every time someone writes Config().
        # We intercept here: if no instance exists yet, create one and load .env.
        # If one already exists, return it — nothing is re-read.
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load()
        return cls._instance

    def _load(self) -> None:
        # Reads the .env file from the project root into os.environ
        load_dotenv()

        # --- Required keys: missing = loud error at startup ---
        self.openai_api_key: str = self._require("OPENAI_API_KEY")
        self.anthropic_api_key: str = self._require("ANTHROPIC_API_KEY")

        # --- Job API keys: optional now, required when Step 2 is built ---
        self.jsearch_api_key: str = self._optional_warn("JSEARCH_API_KEY")
        self.adzuna_app_id: str = os.getenv("ADZUNA_APP_ID", "")
        self.adzuna_app_key: str = os.getenv("ADZUNA_APP_KEY", "")

        # --- Telegram: optional now, required when Step 2 notifications are built ---
        self.telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")

        # --- Company Intel (Step 3) ---
        # Tavily: web search purpose-built for AI agents. Free tier: 1000 queries/month.
        # Sign up at app.tavily.com — takes 30 seconds.
        self.tavily_api_key: str = os.getenv("TAVILY_API_KEY", "")

        # --- Google: optional now, required when Step 3 tracker is built ---
        self.google_sheets_credentials: str = os.getenv("GOOGLE_SHEETS_CREDENTIALS_JSON", "")
        self.google_spreadsheet_id: str = os.getenv("GOOGLE_SPREADSHEET_ID", "")
        self.gmail_credentials: str = os.getenv("GMAIL_CREDENTIALS_JSON", "")

        # --- GitHub: optional, used for persona enrichment in Step 1 ---
        self.github_username: str = os.getenv("GITHUB_USERNAME", "")

        # --- App settings ---
        self.log_level: str = os.getenv("LOG_LEVEL", "INFO")

        # --- LLM model names: centralised here so changing a model = one line change ---
        #
        # VERIFIED 2026-05-02 via tests/test_llm_client.py:
        #   gpt-5-nano     → BROKEN: returns empty string (not yet stable for our use)
        #   gpt-5.4-mini   → PASS plain text + JSON ✓ — cheapest working model
        #   gpt-5          → PASS plain text only, FAIL JSON — use for non-structured tasks only
        #   claude-haiku   → PASS plain text + JSON ✓
        #   claude-sonnet  → PASS plain text + JSON ✓
        #
        # Tasks that need JSON output (scoring, extraction): use gpt-5.4-mini or claude
        # Tasks that produce plain text (messages, persona interview): can use gpt-5
        self.model_nano: str = "gpt-5.4-mini"               # Was gpt-5-nano — broken, upgraded to mini
        self.model_mid: str = "gpt-5.4-mini"                # Company intel, referral ranking, skill normalization
        self.model_quality: str = "gpt-5"                   # Persona builder, cold messages (plain text only)
        self.model_resume: str = "claude-sonnet-4-6"        # Resume bullet rewriting + LaTeX (Claude only)
        self.model_cover: str = "claude-haiku-4-5-20251001" # Cover letter generation

        # --- File paths (all via pathlib — never string concatenation) ---
        self.profile_dir: Path = Path("profile")
        self.profile_path: Path = Path(os.getenv("PROFILE_PATH", "profile/profile.json"))
        self.data_dir: Path = Path("data")
        self.artifacts_dir: Path = self.data_dir / "artifacts"
        self.db_path: Path = self.data_dir / "dossier.db"
        self.prompts_dir: Path = Path("prompts")

    def _require(self, key: str) -> str:
        # Reads a required env var. Raises immediately with a clear message if missing.
        value = os.getenv(key)
        if not value:
            raise ValueError(
                f"\n[Config] Required environment variable '{key}' is missing.\n"
                f"  → Open your .env file and add: {key}=your_value_here\n"
                f"  → See .env.example for the full list with setup instructions."
            )
        return value

    def _optional_warn(self, key: str) -> str:
        # Reads an optional env var. Prints a warning if missing so you know, but doesn't crash.
        value = os.getenv(key, "")
        if not value:
            print(f"[Config] Warning: '{key}' is not set — some features will not work until added to .env.")
        return value
