import json
import os

from dotenv import load_dotenv

load_dotenv()

from anthropic import Anthropic
from gmail_client import GmailClient
from resume_handler import ResumeHandler

SYSTEM_PROMPT = """You are an intelligent email automation agent. Your job is to:

1. Search for recent unread emails using the search_emails tool
2. For each unread email thread that has NOT been processed:
   - Read the full content using get_email_content
   - Determine whether it is a job-related email (contains job description,
     recruitment outreach, interview invitation, or job opportunity details)
   - Draft a professional, personalised reply using create_draft_reply
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
  - Briefly highlight your most relevant qualifications
  - Propose next steps (call, interview, etc.)
  - Keep the tone professional and enthusiastic

For non-job emails:
  - Draft a concise, contextually appropriate professional reply

Work through every unprocessed thread before finishing."""


class EmailAutomationAgent:
    def __init__(self):
        self.client = Anthropic()
        self.gmail = GmailClient()
        self.resume_handler = ResumeHandler()
        self.model = "claude-opus-4-7"

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
                            "description": "Max threads to return (default 10, max 20)",
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
                        "thread_id": {
                            "type": "string",
                            "description": "Gmail thread ID",
                        }
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
                        "to": {
                            "type": "string",
                            "description": "Recipient email address",
                        },
                        "subject": {
                            "type": "string",
                            "description": "Subject line (prefix with 'Re: ' for replies)",
                        },
                        "body": {
                            "type": "string",
                            "description": "Plain-text email body",
                        },
                        "thread_id": {
                            "type": "string",
                            "description": "Thread ID to reply within (optional)",
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
                "description": (
                    "Save a tailored resume for a specific job to the "
                    "tailored_resumes/ directory."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "job_title": {
                            "type": "string",
                            "description": "The role title",
                        },
                        "company": {
                            "type": "string",
                            "description": "The company name",
                        },
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
                "description": (
                    "Record a thread as processed so it is skipped on future runs."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "thread_id": {
                            "type": "string",
                            "description": "Gmail thread ID to mark done",
                        }
                    },
                    "required": ["thread_id"],
                },
            },
        ]

    def _call_tool(self, name: str, inputs: dict) -> str:
        try:
            if name == "search_emails":
                result = self.gmail.search_threads(
                    query=inputs.get("query", "is:unread"),
                    max_results=min(inputs.get("max_results", 10), 20),
                )
            elif name == "get_email_content":
                result = self.gmail.get_thread(inputs["thread_id"])
            elif name == "create_draft_reply":
                result = self.gmail.create_draft(
                    to=inputs["to"],
                    subject=inputs["subject"],
                    body=inputs["body"],
                    thread_id=inputs.get("thread_id"),
                )
            elif name == "get_resume":
                result = self.resume_handler.get_resume()
            elif name == "save_tailored_resume":
                result = self.resume_handler.save_tailored_resume(
                    job_title=inputs["job_title"],
                    company=inputs["company"],
                    resume_content=inputs["resume_content"],
                )
            elif name == "mark_email_processed":
                result = self.gmail.mark_processed(inputs["thread_id"])
            else:
                result = {"error": f"Unknown tool: {name}"}
        except Exception as exc:
            result = {"error": str(exc)}

        return json.dumps(result, ensure_ascii=False)

    def run(self):
        print("=" * 60)
        print("Email Automation Agent — starting")
        print("=" * 60)

        messages = [
            {
                "role": "user",
                "content": (
                    "Please check my recent unread emails. "
                    "For each one, draft a professional reply. "
                    "For any job-related emails, also tailor my resume to match "
                    "the job requirements and save it. "
                    "Mark every email as processed when finished."
                ),
            }
        ]

        while True:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=8096,
                thinking={"type": "adaptive"},
                # Cache the stable system prompt (tools render before system,
                # so this breakpoint caches tools + system together).
                system=[
                    {
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                tools=self._tools(),
                messages=messages,
            )

            print(f"\n[stop_reason={response.stop_reason}]")

            # Show cache stats when available
            usage = response.usage
            if hasattr(usage, "cache_read_input_tokens"):
                print(
                    f"[usage] input={usage.input_tokens} "
                    f"cache_read={usage.cache_read_input_tokens} "
                    f"cache_write={usage.cache_creation_input_tokens} "
                    f"output={usage.output_tokens}"
                )

            tool_uses = []
            for block in response.content:
                if block.type == "thinking":
                    snippet = block.thinking[:150].replace("\n", " ")
                    print(f"[thinking] {snippet}…")
                elif block.type == "text":
                    print(f"\n[agent] {block.text}")
                elif block.type == "tool_use":
                    tool_uses.append(block)
                    args_snippet = json.dumps(block.input)[:120]
                    print(f"\n[tool] {block.name}({args_snippet})")

            if response.stop_reason == "end_turn" or not tool_uses:
                print("\n" + "=" * 60)
                print("Email Automation Agent — done")
                print("=" * 60)
                break

            # Append full assistant turn (preserves thinking blocks for API)
            messages.append({"role": "assistant", "content": response.content})

            # Execute tools and collect results
            tool_results = []
            for tu in tool_uses:
                print(f"[exec] {tu.name}…")
                result_str = self._call_tool(tu.name, tu.input)
                preview = result_str[:300] + ("…" if len(result_str) > 300 else "")
                print(f"[result] {preview}")
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tu.id,
                        "content": result_str,
                    }
                )

            messages.append({"role": "user", "content": tool_results})


if __name__ == "__main__":
    agent = EmailAutomationAgent()
    agent.run()
