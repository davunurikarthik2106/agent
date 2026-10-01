# Email Automation Agent

A local automation that reads your Gmail, drafts personalised replies, and tailors your resume for any job-related emails — all powered by Claude via the Anthropic SDK.

## What it does

1. Searches Gmail for unread threads (configurable query and count)
2. For **every** thread: drafts a professional reply and saves it to Gmail Drafts (never auto-sends)
3. For **job-related** threads (job descriptions, recruiter outreach, interview invites): reads your `resume.txt`, rewrites it to match the role, and saves the result to `tailored_resumes/`
4. Marks each thread as processed so re-runs skip it
5. Supports a `--dry-run` mode that analyses everything without writing any drafts

## Prerequisites

- Python 3.9+
- A Google Cloud project with the **Gmail API** enabled and an OAuth 2.0 credential (`credentials.json`)
- An Anthropic API key

## Quick start

```bash
# 1. Clone and install
git clone <repo> && cd agent
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env → set ANTHROPIC_API_KEY=sk-ant-...

# 3. Add Gmail credentials
# Download credentials.json from Google Cloud Console
# (APIs & Services → Credentials → OAuth 2.0 Client ID → Desktop app)
# Place it in this folder.

# 4. Fill in your resume
# Edit resume.txt with your real experience, skills, and education.

# 5. Run
python agent.py
```

On the **first run** a browser window opens for Gmail OAuth consent. After approval, `token.json` is saved and future runs are fully headless.

## CLI options

```
python agent.py [--query QUERY] [--max N] [--dry-run] [--debug]

  --query   Gmail search query         (default: 'is:unread newer_than:7d')
  --max     Max threads per run         (default: 10)
  --dry-run Analyse without creating drafts or saving resumes
  --debug   Enable DEBUG-level logging
```

**Examples:**

```bash
# Process up to 20 unread emails from the last 3 days
python agent.py --query "is:unread newer_than:3d" --max 20

# Preview what the agent would do without any side effects
python agent.py --dry-run

# Focus on job-related emails only
python agent.py --query "is:unread subject:opportunity OR subject:role OR subject:position"
```

## Configuration via environment variables

All tunables can be set in `.env` instead of CLI flags:

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | **Required.** Your Anthropic API key |
| `AGENT_MODEL` | `claude-opus-4-7` | Claude model to use |
| `AGENT_MAX_TOKENS` | `16000` | Max output tokens per API call |
| `AGENT_QUERY` | `is:unread newer_than:7d` | Default Gmail search query |
| `AGENT_MAX_RESULTS` | `10` | Default thread limit |
| `AGENT_MAX_RETRIES` | `5` | Retries on transient API/Gmail errors |
| `GMAIL_CREDENTIALS_FILE` | `credentials.json` | Path to OAuth client secret |
| `GMAIL_TOKEN_FILE` | `token.json` | Path to saved OAuth token |
| `AGENT_RESUME_FILE` | `resume.txt` | Path to base resume |
| `AGENT_TAILORED_DIR` | `tailored_resumes` | Output directory for tailored resumes |

## Output

| File/Directory | Purpose |
|---|---|
| `tailored_resumes/` | Tailored resumes, one per job (`<company>_<role>_<timestamp>.txt`) |
| `processed_threads.json` | Tracks processed Gmail thread IDs |
| `token.json` | OAuth token (auto-refreshed; **do not commit**) |
| Gmail Drafts folder | All drafted replies — review before sending |

## Project layout

```
agent.py            — CLI entry point + Anthropic agentic loop
gmail_client.py     — Gmail API wrapper (OAuth2, search, draft creation, retries)
email_utils.py      — Pure email parsing (HTML stripping, body extraction)
resume_handler.py   — Reads resume.txt, saves tailored resumes
config.py           — All tunables in one place
requirements.txt    — Python dependencies
.env.example        — Environment variable template
resume.txt          — Your base resume (edit this)
tests/
  test_gmail_client.py   — Unit tests for email parsing and processed-thread logic
  test_resume_handler.py — Unit tests for resume read/write/validation
```

## Running tests

```bash
python -m pytest tests/ -v
```

## Security notes

- `credentials.json` and `token.json` contain sensitive auth data — **do not commit them** (already in `.gitignore`).
- Drafts are never sent automatically; you always review before sending.
- Delete `processed_threads.json` to reprocess all emails from scratch.
