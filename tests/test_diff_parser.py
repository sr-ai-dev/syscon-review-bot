from src.review.diff_parser import parse_diff, parse_pr_files, filter_files, FileDiff
from src.models.config import IgnoreConfig


SAMPLE_DIFF = """diff --git a/src/api/users.py b/src/api/users.py
index abc1234..def5678 100644
--- a/src/api/users.py
+++ b/src/api/users.py
@@ -10,6 +10,8 @@ def get_user(user_id: int):
     user = db.query(User).filter(User.id == user_id).first()
     if not user:
         raise HTTPException(status_code=404)
+    if user.is_deleted:
+        raise HTTPException(status_code=410)
     return user
diff --git a/requirements.lock b/requirements.lock
index 111..222 100644
--- a/requirements.lock
+++ b/requirements.lock
@@ -1,3 +1,4 @@
 fastapi==0.100.0
+httpx==0.24.0
 uvicorn==0.22.0
"""


class TestParseDiff:
    def test_parse_multiple_files(self):
        files = parse_diff(SAMPLE_DIFF)
        assert len(files) == 2
        assert files[0].path == "src/api/users.py"
        assert files[1].path == "requirements.lock"

    def test_parse_patch_content(self):
        files = parse_diff(SAMPLE_DIFF)
        assert "user.is_deleted" in files[0].patch

    def test_parse_additions_counted(self):
        files = parse_diff(SAMPLE_DIFF)
        assert files[0].additions > 0

    def test_empty_diff_returns_empty_list(self):
        assert parse_diff("") == []

    def test_parses_quoted_utf8_rename_destination_path(self):
        diff = (
            'diff --git "a/spec/old-\\352\\270\\260.md" '
            '"b/spec/new-\\352\\270\\260.md"\n'
            "similarity index 100%\n"
            'rename from "spec/old-\\352\\270\\260.md"\n'
            'rename to "spec/new-\\352\\270\\260.md"\n'
        )

        files = parse_diff(diff)

        assert len(files) == 1
        assert files[0].path == "spec/new-기.md"
        assert files[0].previous_path == "spec/old-기.md"
        assert files[0].status == "renamed"
        assert files[0].patch == "rename from spec/old-기.md\nrename to spec/new-기.md"

    def test_marks_binary_diff_without_treating_it_as_text_patch(self):
        files = parse_diff(
            "diff --git a/assets/logo.png b/assets/logo.png\n"
            "Binary files a/assets/logo.png and b/assets/logo.png differ\n"
        )

        assert files[0].is_binary is True
        assert files[0].patch == ""

    def test_counts_content_lines_that_begin_with_multiple_signs(self):
        files = parse_diff(
            "diff --git a/a.txt b/a.txt\n"
            "@@ -1 +1 @@\n"
            "---removed content\n"
            "+++added content\n"
        )

        assert files[0].additions == 1
        assert files[0].deletions == 1


class TestFilterFiles:
    def test_filter_by_extension(self):
        files = parse_diff(SAMPLE_DIFF)
        filtered = filter_files(files, IgnoreConfig(extensions=[".lock"]))
        assert len(filtered) == 1
        assert filtered[0].path == "src/api/users.py"

    def test_filter_by_glob(self):
        files = parse_diff(SAMPLE_DIFF)
        filtered = filter_files(files, IgnoreConfig(files=["*.lock"]))
        assert len(filtered) == 1

    def test_no_filter_keeps_all(self):
        files = parse_diff(SAMPLE_DIFF)
        filtered = filter_files(files, IgnoreConfig())
        assert len(filtered) == 2


class TestParsePrFiles:
    def test_converts_files_api_response(self):
        raw = [
            {
                "filename": "src/api/users.py",
                "patch": "@@ -10,6 +10,8 @@\n+    if user.is_deleted:\n+        raise HTTPException(status_code=410)",
                "additions": 2,
                "deletions": 0,
                "status": "modified",
            },
            {
                "filename": "requirements.lock",
                "patch": "@@ -1,3 +1,4 @@\n+httpx==0.24.0",
                "additions": 1,
                "deletions": 0,
                "status": "modified",
            },
        ]
        files = parse_pr_files(raw)
        assert len(files) == 2
        assert files[0].path == "src/api/users.py"
        assert files[0].additions == 2
        assert "user.is_deleted" in files[0].patch

    def test_skips_files_without_patch(self):
        raw = [
            {"filename": "big.bin", "patch": None, "additions": 0, "deletions": 0, "status": "modified"},
            {"filename": "ok.py", "patch": "@@ -1 +1 @@\n+x", "additions": 1, "deletions": 0, "status": "modified"},
        ]
        files = parse_pr_files(raw)
        assert len(files) == 1
        assert files[0].path == "ok.py"

    def test_empty_input(self):
        assert parse_pr_files([]) == []

    def test_preserves_pure_rename_as_metadata_patch(self):
        files = parse_pr_files([
            {
                "filename": "new.py",
                "previous_filename": "old.py",
                "patch": None,
                "additions": 0,
                "deletions": 0,
                "status": "renamed",
            }
        ])

        assert files[0].path == "new.py"
        assert files[0].previous_path == "old.py"
        assert files[0].patch == "rename from old.py\nrename to new.py"

    def test_removed_files_included(self):
        raw = [
            {"filename": "old.py", "patch": "@@ -1,5 +0,0 @@\n-line1\n-line2", "additions": 0, "deletions": 2, "status": "removed"},
        ]
        files = parse_pr_files(raw)
        assert len(files) == 1
        assert files[0].deletions == 2
