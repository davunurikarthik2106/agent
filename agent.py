"""Email Automation Agent — entry point.

Usage:
    python agent.py [--query QUERY] [--max N] [--dry-run] [--debug]

Options:
    --query   Gmail search query (default: value of AGENT_QUERY env var or 'is:unread newer_than:7d')
    --max     Max threads to process per run (default: AGENT_MAX_RESULTS or 10)
    --dry-run Analyse emails and log what would happen; skip drafts and resume saves
    --debug   Enable DEBUG-level logging
"""

import argparse
import json
import logging
import sys
import time

from dotenv import load_dotenv

load_dotenv()

import anthropic

import config
from gmail_client import GmailClient
from resume_handler import ResumeHandler

# ── Logging setup ──────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("agent")

# ── System prompt ──────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an intelligent email automation agent. Your job is to:

1. Search for recent unread emails using the search_emails tool
2. For each unread email thread that has NOT been processed:
   - Read the full content using get_email_content
   - Determine whether it is a job-related email (contains job description,
     recruitment outreach, interview invitation, or job opportunity details)
   - Draft a professional, personalised reply using create_draft_reply, making
     sure to pass the thread_id and the in_reply_to value from the latest message
   - If the email contains a job description or role requirements:
       * Fetch the current resume via get_resume
       * Rewrite and tailor the resume to highlight relevant experience,
         skills, and achievements that match the job requirements
       * Use exact keywords from the job description
       * Quantify achievements wherever possible
       * Save the tailored resume via save_tailored_resume
   - Mark the thread as processed via mark_email_processed

For job-related replies:
  - Express genuine interest in the role
  - Briefly highlight the most relevant qualifications
  - Propose next steps (call, interview, etc.)
  - Keep the tone professional and enthusiastic

For non-job emails:
  - Draft a concise, contextually appropriate professional reply

Work through every unprocessed thread before finishing.
If dry_run is true in the initial message, skip create_draft_reply and
save_tailored_resume — only log what you would have done."""


class EmailAutomationAgent:
    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.client = anthropic.Anthropic()
        self.gmail = GmailClient()
        self.resume_handler = ResumeHandler()

    # ─────────────────────────────────────── tool schema ──────────────────

    def _tools(self) -> list:
        return [
            {
                "name": "search_emails",
                "description": (
                    "Search Gmail for email threads. Returns basic thread info "
                    "(subject, sender, snippet). Already-processed threads are excluded."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": (
                                "Gmail search query, e.g. 'is:unread', "
                                "'is:unread newer_than:3d', 'subject:opportunity'"
                            ),
                        },
                        "max_results": {
                            "type": "integer",
                            "description": f"Max threads to return (default {config.DEFAULT_MAX_RESULTS}, max {config.MAX_RESULTS_CAP})",
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "get_email_content",
                "description": "Fetch the full text of every message in a Gmail thread.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "thread_id": {"type": "string", "description": "Gmail thread ID"}
                    },
                    "required": ["thread_id"],
                },
            },
            {
                "name": "create_draft_reply",
                "description": (
                    "Create a draft reply in Gmail. The draft appears in the "
                    "Drafts folder and is NOT sent automatically."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "to": {"type": "string", "description": "Recipient email address"},
                        "subject": {
                            "type": "string",
                            "description": "Subject line (prefix 'Re: ' for replies)",
                        },
                        "body": {"type": "string", "description": "Plain-text email body"},
                        "thread_id": {
                            "type": "string",
                            "description": "Gmail thread ID (required for threading)",
                        },
                        "in_reply_to": {
                            "type": "string",
                            "description": "Message-ID header of the message being replied to (e.g. '<abc@mail.gmail.com>')",
                        },
                        "references": {
                            "type": "string",
                            "description": "Space-separated list of Message-ID headers for the full thread chain",
                        },
                    },
                    "required": ["to", "subject", "body"],
                },
            },
            {
                "name": "get_resume",
                "description": "Read the current resume from the local resume.txt file.",
                "input_schema": {"type": "object", "properties": {}},
            },
            {
                "name": "save_tailored_resume",
                "description": "Save a tailored resume for a specific job to the tailored_resumes/ directory.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "job_title": {"type": "string", "description": "The role title"},
                        "company": {"type": "string", "description": "The company name"},
                        "resume_content": {
                            "type": "string",
                            "description": "Full tailored resume as plain text",
                        },
                    },
                    "required": ["job_title", "company", "resume_content"],
                },
            },
            {
                "name": "mark_email_processed",
                "description": "Record a thread as processed so it is skipped on future runs.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "thread_id": {"type": "string", "description": "Gmail thread ID to mark done"}
                    },
                    "required": ["thread_id"],
                },
            },
        ]

    # ─────────────────────────────────────── tool execution ───────────────

    def _call_tool(self, name: str, inputs: dict) -> str:
        try:
            result = self._dispatch(name, inputs)
        except Exception as exc:
            log.exception("Unhandled error in tool %s", name)
            result = {"error": str(exc)}
        return json.dumps(result, ensure_ascii=False)

    def _dispatch(self, name: str, inputs: dict) -> dict:
        if name == "search_emails":
            return self.gmail.search_threads(
                query=inputs.get("query", config.DEFAULT_QUERY),
                max_results=min(inputs.get("max_results", config.DEFAULT_MAX_RESULTS), config.MAX_RESULTS_CAP),
            )

        if name == "get_email_content":
            return self.gmail.get_thread(inputs["thread_id"])

        if name == "create_draft_reply":
            if self.dry_run:
                log.info("[dry-run] Would create draft → to=%s subject=%s", inputs.get("to"), inputs.get("subject"))
                return {"status": "dry_run", "skipped": True}
            return self.gmail.create_draft(
                to=inputs["to"],
                subject=inputs["subject"],
                body=inputs["body"],
                thread_id=inputs.get("thread_id"),
                in_reply_to=inputs.get("in_reply_to"),
                references=inputs.get("references"),
            )

        if name == "get_resume":
            return self.resume_handler.get_resume()

        if name == "save_tailored_resume":
            if self.dry_run:
                log.info(
                    "[dry-run] Would save tailored resume for %s @ %s",
                    inputs.get("job_title"),
                    inputs.get("company"),
                )
                return {"status": "dry_run", "skipped": True}
            return self.resume_handler.save_tailored_resume(
                job_title=inputs["job_title"],
                company=inputs["company"],
                resume_content=inputs["resume_content"],
            )

        if name == "mark_email_processed":
            return self.gmail.mark_processed(inputs["thread_id"])

        return {"error": f"Unknown tool: {name}"}

    # ─────────────────────────────────────── agentic loop ─────────────────

    def run(self, query: str, max_results: int):
        log.info("Email Automation Agent starting (model=%s, dry_run=%s)", config.MODEL, self.dry_run)

        user_msg = (
            f"Please check my recent unread emails using query '{query}' "
            f"(up to {max_results} threads). "
            "For each one, draft a professional reply. "
            "For any job-related emails, also tailor my resume to match "
            "the job requirements and save it. "
            "Mark every email as processed when finished."
        )
        if self.dry_run:
            user_msg += " dry_run is true — skip drafts and resume saves, just log what you would do."

        messages: list[dict] = [{"role": "user", "content": user_msg}]
        iteration = 0

        while True:
            iteration += 1
            log.debug("API call iteration %d", iteration)

            response = self._api_call_with_retry(messages)

            log.info("stop_reason=%s", response.stop_reason)
            usage = response.usage
            log.info(
                "tokens — input=%d cache_read=%s cache_write=%s output=%d",
                usage.input_tokens,
                getattr(usage, "cache_read_input_tokens", "n/a"),
                getattr(usage, "cache_creation_input_tokens", "n/a"),
                usage.output_tokens,
            )

            tool_uses = []
            for block in response.content:
                if block.type == "thinking":
                    snippet = block.thinking[:200].replace("\n", " ") if block.thinking else ""
                    log.debug("[thinking] %s…", snippet)
                elif block.type == "text":
                    log.info("[agent] %s", block.text)
                elif block.type == "tool_use":
                    tool_uses.append(block)
                    log.info("[tool] %s(%s)", block.name, json.dumps(block.input)[:160])

            if response.stop_reason == "end_turn" or not tool_uses:
                log.info("Agent finished after %d iteration(s).", iteration)
                break

            # Preserve full assistant turn (keeps thinking blocks intact for API)
            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for tu in tool_uses:
                log.info("[exec] %s", tu.name)
                result_str = self._call_tool(tu.name, tu.input)
                preview = result_str[:400] + ("…" if len(result_str) > 400 else "")
                log.info("[result] %s", preview)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": result_str,
                    }
                )

            messages.append({"role": "user", "content": tool_results})

    def _api_call_with_retry(self, messages: list) -> anthropic.types.Message:
        delay = config.RETRY_BASE_DELAY
        for attempt in range(config.MAX_RETRIES):
            try:
                return self.client.messages.create(
                    model=config.MODEL,
                    max_tokens=config.MAX_TOKENS,
                    thinking={"type": "adaptive"},
                    system=[
                        {
                            "type": "text",
                            "text": SYSTEM_PROMPT,
                            # caches tools + system (render order: tools → system → messages)
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    tools=self._tools(),
                    messages=messages,
                )
            except anthropic.RateLimitError as exc:
                if attempt < config.MAX_RETRIES - 1:
                    log.warning("Rate limited, retry %d/%d in %.1fs", attempt + 1, config.MAX_RETRIES, delay)
                    time.sleep(delay)
                    delay = min(delay * 2, 60)
                else:
                    raise
            except anthropic.APIStatusError as exc:
                if exc.status_code >= 500 and attempt < config.MAX_RETRIES - 1:
                    log.warning("API %d error, retry %d/%d in %.1fs", exc.status_code, attempt + 1, config.MAX_RETRIES, delay)
                    time.sleep(delay)
                    delay = min(delay * 2, 60)
                else:
                    raise

        raise RuntimeError("Exhausted retries")  # unreachable, satisfies type checkers


# ── CLI ────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Email Automation Agent — drafts replies and tailors resumes for job emails."
    )
    p.add_argument(
        "--query",
        default=config.DEFAULT_QUERY,
        help=f"Gmail search query (default: '{config.DEFAULT_QUERY}')",
    )
    p.add_argument(
        "--max",
        type=int,
        default=config.DEFAULT_MAX_RESULTS,
        dest="max_results",
        help=f"Max threads to process (default: {config.DEFAULT_MAX_RESULTS})",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Analyse emails without creating drafts or saving resumes",
    )
    p.add_argument(
        "--debug",
        action="store_true",
        help="Enable DEBUG-level logging",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        agent = EmailAutomationAgent(dry_run=args.dry_run)
        agent.run(query=args.query, max_results=args.max_results)
    except KeyboardInterrupt:
        log.info("Interrupted by user.")
        sys.exit(0)
    except FileNotFoundError as exc:
        log.error("%s", exc)
        sys.exit(1)
    except Exception:
        log.exception("Fatal error")
        sys.exit(1)
