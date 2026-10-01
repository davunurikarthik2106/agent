# Email Automation Agent

A local automation that reads your Gmail, drafts personalised replies, and tailors your resume for any job-related emails — all powered by Claude via the Anthropic SDK.

## What it does

1. Searches Gmail for unread threads
2. For **every** thread: drafts a professional reply and saves it to Gmail Drafts (never auto-sends)
3. For **job-related** threads (job descriptions, recruiter outreach, interview invites): reads your `resume.txt`, rewrites it to match the role, and saves the result to `tailored_resumes/`
4. Marks each thread as processed so re-runs skip it

## Prerequisites

- Python 3.9+
- A Google Cloud project with the **Gmail API** enabled and an OAuth 2.0 credential (`credentials.json`)
- An Anthropic API key

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Open .env and set ANTHROPIC_API_KEY=<your key>
```

### 3. Add Gmail credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → APIs & Services → Credentials
2. Create an **OAuth 2.0 Client ID** (Desktop app)
3. Download the JSON and save it as `credentials.json` in this folder
4. Add your Gmail address to the OAuth consent screen test users

### 4. Fill in your resume

Edit `resume.txt` and replace the template with your real information. This is what the agent reads and tailors per job.

## Running

```bash
python agent.py
```

On the **first run** a browser window opens for Gmail OAuth consent. After you approve, a `token.json` is saved and future runs are fully headless.

## Output

| File/Directory | Purpose |
|---|---|
| `tailored_resumes/` | Tailored resumes, one file per job (`<company>_<role>_<timestamp>.txt`) |
| `processed_threads.json` | Tracks which Gmail thread IDs have been handled |
| `token.json` | OAuth token (auto-refreshed; do not commit) |
| Gmail Drafts folder | All drafted replies live here for your review before sending |

## File overview

```
agent.py            — Anthropic SDK agentic loop (6 tools, adaptive thinking, prompt caching)
gmail_client.py     — Gmail API wrapper (OAuth2, thread search, draft creation)
resume_handler.py   — Reads resume.txt, saves tailored resumes
resume.txt          — Your base resume (edit this)
requirements.txt    — Python dependencies
.env.example        — Environment variable template
```

## Security notes

- `credentials.json` and `token.json` contain sensitive auth data — **do not commit them**. A `.gitignore` entry is recommended.
- Drafts are never sent automatically; you always review before sending.
- `processed_threads.json` is safe to delete if you want to reprocess all emails from scratch.
