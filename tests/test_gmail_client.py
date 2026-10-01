"""Unit tests for Gmail-related logic — no network, no broken C extensions."""
import base64
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


# ── HTML stripping (pure — no Google Auth dependency) ──────────────────────

class TestHTMLStripper(unittest.TestCase):
    def test_strips_tags(self):
        from email_utils import strip_html
        result = strip_html("<p>Hello <b>World</b></p>")
        self.assertIn("Hello", result)
        self.assertIn("World", result)
        self.assertNotIn("<", result)

    def test_strips_script_content(self):
        from email_utils import strip_html
        result = strip_html("<script>alert('xss')</script>Hello")
        self.assertNotIn("alert", result)
        self.assertIn("Hello", result)

    def test_strips_style_content(self):
        from email_utils import strip_html
        result = strip_html("<style>body{color:red}</style>Text")
        self.assertNotIn("color", result)
        self.assertIn("Text", result)

    def test_empty_input(self):
        from email_utils import strip_html
        self.assertEqual(strip_html(""), "")

    def test_plain_text_passthrough(self):
        from email_utils import strip_html
        self.assertEqual(strip_html("No tags here"), "No tags here")


# ── Body extraction (pure — no Google Auth dependency) ─────────────────────

class TestExtractBody(unittest.TestCase):
    def test_plain_text_payload(self):
        from email_utils import extract_body
        payload = {"body": {"data": _b64("Hello from plain text")}}
        self.assertEqual(extract_body(payload), "Hello from plain text")

    def test_multipart_prefers_plain(self):
        from email_utils import extract_body
        payload = {
            "parts": [
                {"mimeType": "text/plain", "body": {"data": _b64("Plain text")}},
                {"mimeType": "text/html", "body": {"data": _b64("<p>HTML</p>")}},
            ]
        }
        self.assertEqual(extract_body(payload), "Plain text")

    def test_multipart_falls_back_to_html(self):
        from email_utils import extract_body
        payload = {
            "parts": [
                {"mimeType": "text/html", "body": {"data": _b64("<p>Only HTML</p>")}},
            ]
        }
        self.assertIn("Only HTML", extract_body(payload))

    def test_empty_payload(self):
        from email_utils import extract_body
        self.assertEqual(extract_body({}), "")

    def test_nested_multipart(self):
        from email_utils import extract_body
        payload = {
            "parts": [
                {
                    "mimeType": "multipart/alternative",
                    "parts": [
                        {"mimeType": "text/plain", "body": {"data": _b64("Nested plain")}},
                    ],
                }
            ]
        }
        self.assertIn("Nested plain", extract_body(payload))

    def test_body_cap_not_exceeded(self):
        from email_utils import extract_body
        long_text = "A" * 20000
        payload = {"body": {"data": _b64(long_text)}}
        # extract_body itself doesn't cap — the cap is applied in GmailClient
        self.assertEqual(len(extract_body(payload)), 20000)


# ── Processed-thread persistence ───────────────────────────────────────────

# Mock out the entire google.auth chain before importing gmail_client
_GOOGLE_MOCKS = {
    "google": MagicMock(),
    "google.auth": MagicMock(),
    "google.auth.transport": MagicMock(),
    "google.auth.transport.requests": MagicMock(),
    "google.oauth2": MagicMock(),
    "google.oauth2.credentials": MagicMock(),
    "google_auth_oauthlib": MagicMock(),
    "google_auth_oauthlib.flow": MagicMock(),
    "googleapiclient": MagicMock(),
    "googleapiclient.discovery": MagicMock(),
    "googleapiclient.errors": MagicMock(),
}


class TestMarkProcessed(unittest.TestCase):
    def setUp(self):
        self.patcher = patch.dict(sys.modules, _GOOGLE_MOCKS)
        self.patcher.start()
        # Ensure gmail_client is reimported with mocked modules
        sys.modules.pop("gmail_client", None)

    def tearDown(self):
        self.patcher.stop()
        sys.modules.pop("gmail_client", None)

    def _make_client(self, processed_file: str):
        config.PROCESSED_FILE = processed_file
        from gmail_client import GmailClient

        with patch.object(GmailClient, "_authenticate", return_value=MagicMock()), \
             patch.object(GmailClient, "_load_processed", return_value=set()):
            return GmailClient()

    def test_adds_thread_to_set(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            pfile = f.name
        try:
            client = self._make_client(pfile)
            result = client.mark_processed("thread123")
            self.assertEqual(result["status"], "success")
            self.assertIn("thread123", client.processed)
        finally:
            os.unlink(pfile)

    def test_persists_to_json(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            pfile = f.name
        try:
            client = self._make_client(pfile)
            client.mark_processed("thread_abc")
            with open(pfile) as fh:
                saved = json.load(fh)
            self.assertIn("thread_abc", saved)
        finally:
            os.unlink(pfile)

    def test_multiple_threads_accumulated(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            pfile = f.name
        try:
            client = self._make_client(pfile)
            client.mark_processed("t1")
            client.mark_processed("t2")
            client.mark_processed("t3")
            self.assertEqual(client.processed, {"t1", "t2", "t3"})
            with open(pfile) as fh:
                saved = set(json.load(fh))
            self.assertEqual(saved, {"t1", "t2", "t3"})
        finally:
            os.unlink(pfile)


if __name__ == "__main__":
    unittest.main()
