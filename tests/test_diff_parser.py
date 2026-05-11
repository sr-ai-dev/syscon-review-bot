from src.review.diff_parser import parse_diff, filter_files, FileDiff
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
