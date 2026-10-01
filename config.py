"""Central configuration — all tunables in one place.

Values are read from environment variables (via .env) with sensible defaults.
"""
import os

# ── Anthropic ──────────────────────────────────────────────────────────────
MODEL = os.getenv("AGENT_MODEL", "claude-opus-4-7")
MAX_TOKENS = int(os.getenv("AGENT_MAX_TOKENS", "16000"))

# ── Gmail search ───────────────────────────────────────────────────────────
DEFAULT_QUERY = os.getenv("AGENT_QUERY", "is:unread newer_than:7d")
DEFAULT_MAX_RESULTS = int(os.getenv("AGENT_MAX_RESULTS", "10"))
MAX_RESULTS_CAP = 20          # hard ceiling regardless of user input
BODY_CHAR_LIMIT = 8000        # max chars per message body sent to the model

# ── Retry / rate-limit ─────────────────────────────────────────────────────
MAX_RETRIES = int(os.getenv("AGENT_MAX_RETRIES", "5"))
RETRY_BASE_DELAY = float(os.getenv("AGENT_RETRY_BASE_DELAY", "1.0"))  # seconds

# ── Paths ──────────────────────────────────────────────────────────────────
CREDENTIALS_FILE = os.getenv("GMAIL_CREDENTIALS_FILE", "credentials.json")
TOKEN_FILE = os.getenv("GMAIL_TOKEN_FILE", "token.json")
PROCESSED_FILE = os.getenv("AGENT_PROCESSED_FILE", "processed_threads.json")
RESUME_FILE = os.getenv("AGENT_RESUME_FILE", "resume.txt")
TAILORED_DIR = os.getenv("AGENT_TAILORED_DIR", "tailored_resumes")
