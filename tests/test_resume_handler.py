"""Unit tests for resume_handler.py — no network, no disk side-effects."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config


class TestResumeHandler(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        # Redirect all file paths into the temp directory
        config.RESUME_FILE = os.path.join(self.tmp.name, "resume.txt")
        config.TAILORED_DIR = os.path.join(self.tmp.name, "tailored_resumes")

        # Import after patching config
        from resume_handler import ResumeHandler
        self.handler = ResumeHandler()

    def tearDown(self):
        self.tmp.cleanup()

    def _write_resume(self, content: str):
        with open(config.RESUME_FILE, "w") as f:
            f.write(content)

    # ── get_resume ─────────────────────────────────────────────────────────

    def test_get_resume_missing_file(self):
        result = self.handler.get_resume()
        self.assertIn("error", result)
        self.assertIn("not found", result["error"])

    def test_get_resume_empty_file(self):
        self._write_resume("   \n  ")
        result = self.handler.get_resume()
        self.assertIn("error", result)
        self.assertIn("empty", result["error"])

    def test_get_resume_success(self):
        self._write_resume("John Doe\nSoftware Engineer\n5 years experience")
        result = self.handler.get_resume()
        self.assertEqual(result["status"], "success")
        self.assertIn("John Doe", result["resume"])

    # ── save_tailored_resume ───────────────────────────────────────────────

    def test_save_creates_file(self):
        result = self.handler.save_tailored_resume(
            job_title="Software Engineer",
            company="Acme Corp",
            resume_content="Tailored resume content here.",
        )
        self.assertEqual(result["status"], "success")
        self.assertTrue(os.path.exists(result["file"]))

    def test_save_file_contains_content(self):
        content = "Tailored resume for Acme Corp."
        result = self.handler.save_tailored_resume("SWE", "Acme", content)
        with open(result["file"]) as f:
            saved = f.read()
        self.assertEqual(saved, content)

    def test_save_empty_content_returns_error(self):
        result = self.handler.save_tailored_resume("SWE", "Acme", "   ")
        self.assertIn("error", result)

    def test_save_slugifies_filename(self):
        result = self.handler.save_tailored_resume(
            job_title="Data Scientist / ML",
            company="Big & Bold Co.",
            resume_content="content",
        )
        filename = os.path.basename(result["file"])
        # Filename should only contain safe characters
        self.assertRegex(filename, r'^[a-z0-9_\-]+\.txt$')

    def test_tailored_dir_created(self):
        import shutil
        shutil.rmtree(config.TAILORED_DIR, ignore_errors=True)
        from resume_handler import ResumeHandler
        ResumeHandler()  # __init__ should create it
        self.assertTrue(os.path.isdir(config.TAILORED_DIR))


if __name__ == "__main__":
    unittest.main()
