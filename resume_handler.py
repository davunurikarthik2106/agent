import logging
import os
import re
from datetime import datetime

import config

log = logging.getLogger(__name__)

_TEMPLATE_SENTINEL = "YOUR NAME"  # placeholder text that means resume.txt was never filled in


class ResumeHandler:
    def __init__(self):
        os.makedirs(config.TAILORED_DIR, exist_ok=True)

    def get_resume(self) -> dict:
        if not os.path.exists(config.RESUME_FILE):
            return {
                "error": (
                    f"'{config.RESUME_FILE}' not found. "
                    "Edit it with your real resume content before running the agent."
                )
            }
        with open(config.RESUME_FILE, encoding="utf-8") as fh:
            content = fh.read().strip()

        if not content:
            return {"error": f"'{config.RESUME_FILE}' is empty. Add your resume content."}

        if _TEMPLATE_SENTINEL in content:
            log.warning(
                "%s still contains template placeholder text — "
                "fill it in for best results.",
                config.RESUME_FILE,
            )

        return {"status": "success", "resume": content}

    def save_tailored_resume(
        self, job_title: str, company: str, resume_content: str
    ) -> dict:
        if not resume_content.strip():
            return {"error": "resume_content is empty — nothing saved."}

        slug = _slugify(f"{company}_{job_title}")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{slug}_{timestamp}.txt"
        filepath = os.path.join(config.TAILORED_DIR, filename)

        with open(filepath, "w", encoding="utf-8") as fh:
            fh.write(resume_content)

        log.info("Tailored resume saved: %s", filepath)
        return {
            "status": "success",
            "file": filepath,
            "job_title": job_title,
            "company": company,
        }


def _slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s]+", "_", text.strip())
    text = re.sub(r"-{2,}", "-", text)
    return text[:80]  # cap length to stay within filesystem limits
