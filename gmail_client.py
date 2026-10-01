import base64
import json
import logging
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import config
from email_utils import extract_body as _extract_body_util, strip_html as _strip_html

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]

# HTTP status codes that are safe to retry
_RETRYABLE = {429, 500, 502, 503, 504}


def _retry(fn, *args, **kwargs):
    """Call fn(*args, **kwargs), retrying on transient Gmail API errors."""
    delay = config.RETRY_BASE_DELAY
    for attempt in range(config.MAX_RETRIES):
        try:
            return fn(*args, **kwargs)
        except HttpError as exc:
            if exc.resp.status in _RETRYABLE and attempt < config.MAX_RETRIES - 1:
                log.warning(
                    "Gmail API %s error, retry %d/%d in %.1fs",
                    exc.resp.status,
                    attempt + 1,
                    config.MAX_RETRIES,
                    delay,
                )
                time.sleep(delay)
                delay = min(delay * 2, 60)
            else:
                raise


class GmailClient:
    def __init__(self):
        self.service = self._authenticate()
        self.processed = self._load_processed()

    # ------------------------------------------------------------------ auth

    def _authenticate(self):
        creds = None
        if __import__("os").path.exists(config.TOKEN_FILE):
            creds = Credentials.from_authorized_user_file(config.TOKEN_FILE, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                log.info("Refreshing OAuth token…")
                creds.refresh(Request())
            else:
                import os
                if not os.path.exists(config.CREDENTIALS_FILE):
                    raise FileNotFoundError(
                        f"'{config.CREDENTIALS_FILE}' not found. "
                        "Download it from Google Cloud Console "
                        "(APIs & Services → Credentials → OAuth 2.0 Client)."
                    )
                log.info("Opening browser for Gmail OAuth consent…")
                flow = InstalledAppFlow.from_client_secrets_file(
                    config.CREDENTIALS_FILE, SCOPES
                )
                creds = flow.run_local_server(port=0)
            with open(config.TOKEN_FILE, "w") as fh:
                fh.write(creds.to_json())
            log.info("OAuth token saved to %s", config.TOKEN_FILE)

        return build("gmail", "v1", credentials=creds)

    # ---------------------------------------------------------- processed set

    def _load_processed(self) -> set:
        import os
        if os.path.exists(config.PROCESSED_FILE):
            with open(config.PROCESSED_FILE) as fh:
                return set(json.load(fh))
        return set()

    def _save_processed(self):
        with open(config.PROCESSED_FILE, "w") as fh:
            json.dump(sorted(self.processed), fh, indent=2)

    # --------------------------------------------------------------- threads

    def search_threads(self, query: str = "is:unread", max_results: int = 10) -> dict:
        max_results = min(max_results, config.MAX_RESULTS_CAP)
        try:
            resp = _retry(
                self.service.users().threads().list(
                    userId="me", q=query, maxResults=max_results
                ).execute
            )
            raw_threads = resp.get("threads", [])
            threads = []

            for t in raw_threads:
                if t["id"] in self.processed:
                    continue

                meta = _retry(
                    self.service.users().threads().get(
                        userId="me",
                        id=t["id"],
                        format="metadata",
                        metadataHeaders=["Subject", "From", "To", "Date", "Message-ID"],
                    ).execute
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
                        "latest_message_id": latest["id"],
                        "message_id_header": hdrs.get("Message-ID", ""),
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
            log.error("search_threads failed: %s", exc)
            return {"error": str(exc)}

    def get_thread(self, thread_id: str) -> dict:
        try:
            thread = _retry(
                self.service.users().threads().get(
                    userId="me", id=thread_id, format="full"
                ).execute
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
                        "message_id_header": hdrs.get("Message-ID", ""),
                        "from": hdrs.get("From", ""),
                        "to": hdrs.get("To", ""),
                        "subject": hdrs.get("Subject", ""),
                        "date": hdrs.get("Date", ""),
                        "body": body[: config.BODY_CHAR_LIMIT],
                    }
                )

            return {
                "thread_id": thread_id,
                "message_count": len(messages),
                "messages": messages,
            }

        except HttpError as exc:
            log.error("get_thread %s failed: %s", thread_id, exc)
            return {"error": str(exc)}

    def _extract_body(self, payload: dict) -> str:
        return _extract_body_util(payload)

    # ----------------------------------------------------------------- drafts

    def create_draft(
        self,
        to: str,
        subject: str,
        body: str,
        thread_id: str | None = None,
        in_reply_to: str | None = None,
        references: str | None = None,
    ) -> dict:
        try:
            msg = MIMEMultipart("alternative")
            msg["to"] = to
            msg["subject"] = subject
            if in_reply_to:
                msg["In-Reply-To"] = in_reply_to
            if references:
                msg["References"] = references

            msg.attach(MIMEText(body, "plain", "utf-8"))

            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            draft_body: dict = {"message": {"raw": raw}}
            if thread_id:
                draft_body["message"]["threadId"] = thread_id

            draft = _retry(
                self.service.users().drafts().create(
                    userId="me", body=draft_body
                ).execute
            )

            log.info("Draft created: id=%s to=%s subject=%s", draft["id"], to, subject)
            return {
                "status": "success",
                "draft_id": draft["id"],
                "to": to,
                "subject": subject,
            }

        except HttpError as exc:
            log.error("create_draft failed: %s", exc)
            return {"error": str(exc)}

    # --------------------------------------------------------------- helpers

    def mark_processed(self, thread_id: str) -> dict:
        self.processed.add(thread_id)
        self._save_processed()
        log.info("Thread %s marked as processed", thread_id)
        return {"status": "success", "thread_id": thread_id}
