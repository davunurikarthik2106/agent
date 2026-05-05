import os
from datetime import datetime

RESUME_FILE = "resume.txt"
TAILORED_DIR = "tailored_resumes"


class ResumeHandler:
    def __init__(self):
        os.makedirs(TAILORED_DIR, exist_ok=True)

    def get_resume(self) -> dict:
        if not os.path.exists(RESUME_FILE):
            return {
                "error": f"'{RESUME_FILE}' not found. "
                "Create it with your resume content before running the agent."
            }
        with open(RESUME_FILE, encoding="utf-8") as fh:
            content = fh.read()
        return {"status": "success", "resume": content}

    def save_tailored_resume(
        self, job_title: str, company: str, resume_content: str
    ) -> dict:
        slug = (
            f"{company}_{job_title}"
            .lower()
            .replace(" ", "_")
            .replace("/", "-")
        )
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{slug}_{timestamp}.txt"
        filepath = os.path.join(TAILORED_DIR, filename)

        with open(filepath, "w", encoding="utf-8") as fh:
            fh.write(resume_content)

        return {
            "status": "success",
            "file": filepath,
            "job_title": job_title,
            "company": company,
        }
