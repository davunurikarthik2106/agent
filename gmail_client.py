import base64
import json
import os
import re
from email.mime.text import MIMEText

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
PROCESSED_FILE = "processed_threads.json"
CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.json"


class GmailClient:
    def __init__(self):
        self.service = self._authenticate()
        self.processed = self._load_processed()

    # ------------------------------------------------------------------ auth

    def _authenticate(self):
        creds = None
        if os.path.exists(TOKEN_FILE):
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists(CREDENTIALS_FILE):
                    raise FileNotFoundError(
                        f"'{CREDENTIALS_FILE}' not found. "
                        "Download it from Google Cloud Console "
                        "(APIs & Services → Credentials → OAuth 2.0 Client)."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    CREDENTIALS_FILE, SCOPES
                )
                creds = flow.run_local_server(port=0)
            with open(TOKEN_FILE, "w") as fh:
                fh.write(creds.to_json())

        return build("gmail", "v1", credentials=creds)

    # ---------------------------------------------------------- processed set

    def _load_processed(self) -> set:
        if os.path.exists(PROCESSED_FILE):
            with open(PROCESSED_FILE) as fh:
                return set(json.load(fh))
        return set()

    def _save_processed(self):
        with open(PROCESSED_FILE, "w") as fh:
            json.dump(list(self.processed), fh)

    # --------------------------------------------------------------- threads

    def search_threads(self, query: str = "is:unread", max_results: int = 10) -> dict:
        try:
            resp = (
                self.service.users()
                .threads()
                .list(userId="me", q=query, maxResults=max_results)
                .execute()
            )
            raw_threads = resp.get("threads", [])
            threads = []

            for t in raw_threads:
                if t["id"] in self.processed:
                    continue

                meta = (
                    self.service.users()
                    .threads()
                    .get(
                        userId="me",
                        id=t["id"],
                        format="metadata",
                        metadataHeaders=["Subject", "From", "To", "Date"],
                    )
                    .execute()
                )

                msgs = meta.get("messages", [])
                if not msgs:
                    continue

                latest = msgs[-1]
                hdrs = {
                    h["name"]: h["value"]
                    for h in latest.get("payload", {}).get("headers", [])
                }
                threads.append(
                    {
                        "thread_id": t["id"],
                        "subject": hdrs.get("Subject", "(no subject)"),
                        "from": hdrs.get("From", ""),
                        "to": hdrs.get("To", ""),
                        "date": hdrs.get("Date", ""),
                        "snippet": latest.get("snippet", ""),
                    }
                )

            return {
                "threads": threads,
                "total_matched": len(raw_threads),
                "unprocessed": len(threads),
            }

        except HttpError as exc:
            return {"error": str(exc)}

    def get_thread(self, thread_id: str) -> dict:
        try:
            thread = (
                self.service.users()
                .threads()
                .get(userId="me", id=thread_id, format="full")
                .execute()
            )

            messages = []
            for msg in thread.get("messages", []):
                hdrs = {
                    h["name"]: h["value"]
                    for h in msg.get("payload", {}).get("headers", [])
                }
                body = self._extract_body(msg.get("payload", {}))
                messages.append(
                    {
                        "message_id": msg["id"],
                        "from": hdrs.get("From", ""),
                        "to": hdrs.get("To", ""),
                        "subject": hdrs.get("Subject", ""),
                        "date": hdrs.get("Date", ""),
                        # Cap at 6 000 chars to stay within reasonable token budgets
                        "body": body[:6000],
                    }
                )

            return {
                "thread_id": thread_id,
                "message_count": len(messages),
                "messages": messages,
            }

        except HttpError as exc:
            return {"error": str(exc)}

    def _extract_body(self, payload: dict) -> str:
        """Recursively extract plain-text body; fall back to stripped HTML."""
        if "parts" in payload:
            plain = ""
            html = ""
            for part in payload["parts"]:
                mime = part.get("mimeType", "")
                if mime == "text/plain":
                    data = part.get("body", {}).get("data", "")
                    if data:
                        plain += base64.urlsafe_b64decode(data).decode(
                            "utf-8", errors="ignore"
                        )
                elif mime == "text/html" and not plain:
                    data = part.get("body", {}).get("data", "")
                    if data:
                        raw_html = base64.urlsafe_b64decode(data).decode(
                            "utf-8", errors="ignore"
                        )
                        html += re.sub(r"<[^>]+>", " ", raw_html)
                elif "parts" in part:
                    sub = self._extract_body(part)
                    if sub:
                        plain += sub
            return (plain or html).strip()

        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore").strip()
        return ""

    # ----------------------------------------------------------------- drafts

    def create_draft(
        self, to: str, subject: str, body: str, thread_id: str = None
    ) -> dict:
        try:
            msg = MIMEText(body, "plain", "utf-8")
            msg["to"] = to
            msg["subject"] = subject

            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            draft_body: dict = {"message": {"raw": raw}}
            if thread_id:
                draft_body["message"]["threadId"] = thread_id

            draft = (
                self.service.users()
                .drafts()
                .create(userId="me", body=draft_body)
                .execute()
            )

            return {
                "status": "success",
                "draft_id": draft["id"],
                "to": to,
                "subject": subject,
            }

        except HttpError as exc:
            return {"error": str(exc)}

    # --------------------------------------------------------------- helpers

    def mark_processed(self, thread_id: str) -> dict:
        self.processed.add(thread_id)
        self._save_processed()
        return {"status": "success", "thread_id": thread_id}
