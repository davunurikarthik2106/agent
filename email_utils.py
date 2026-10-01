"""Pure email parsing utilities — no network or auth dependencies."""
import base64
from html.parser import HTMLParser


class _HTMLStripper(HTMLParser):
    """Collect visible text from HTML, discarding tags and scripts."""

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip = True

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = False
        if tag in ("p", "br", "div", "li", "tr"):
            self._parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self._parts.append(data)

    def get_text(self) -> str:
        return " ".join("".join(self._parts).split())


def strip_html(html: str) -> str:
    stripper = _HTMLStripper()
    stripper.feed(html)
    return stripper.get_text()


def extract_body(payload: dict) -> str:
    """Recursively extract plain-text body from a Gmail message payload."""
    if "parts" in payload:
        plain = ""
        html = ""
        for part in payload["parts"]:
            mime = part.get("mimeType", "")
            if mime == "text/plain":
                data = part.get("body", {}).get("data", "")
                if data:
                    plain += base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
            elif mime == "text/html":
                data = part.get("body", {}).get("data", "")
                if data:
                    raw_html = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
                    html += strip_html(raw_html)
            elif "parts" in part:
                sub = extract_body(part)
                if sub:
                    plain += sub
        return (plain or html).strip()

    data = payload.get("body", {}).get("data", "")
    if data:
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore").strip()
    return ""
