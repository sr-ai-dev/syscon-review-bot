"""Tests for spec documentation check."""

from src.spec_check import check_spec_files


class TestCheckSpecFiles:
    def test_no_spec_files_fails(self):
        result = check_spec_files(["src/main.py", "README.md"])
        assert not result.ok
        assert "spec 문서 변경이 없습니다" in result.message
        assert "requirements.md 또는 design.md 중 1개 이상" in result.message

    def test_empty_file_list_fails(self):
        result = check_spec_files([])
        assert not result.ok

    def test_requirements_passes(self):
        files = [
            "spec/login/requirements.md",
            "src/auth.py",
        ]
        result = check_spec_files(files)
        assert result.ok
        assert "login" in result.message

    def test_design_passes(self):
        files = [
            "spec/login/design.md",
            "src/auth.py",
        ]
        result = check_spec_files(files)
        assert result.ok
        assert "login" in result.message

    def test_task_and_requirements_passes(self):
        files = [
            "spec/login/requirements.md",
            "spec/login/task.md",
            "src/auth.py",
        ]
        result = check_spec_files(files)
        assert result.ok
        assert "login" in result.message

    def test_task_and_design_passes(self):
        files = [
            "spec/login/design.md",
            "spec/login/task.md",
            "src/auth.py",
        ]
        result = check_spec_files(files)
        assert result.ok
        assert "login" in result.message

    def test_all_three_passes(self):
        files = [
            "spec/login/requirements.md",
            "spec/login/design.md",
            "spec/login/tasks.md",
        ]
        result = check_spec_files(files)
        assert result.ok

    def test_requirements_and_design_without_tasks_passes(self):
        files = [
            "spec/login/requirements.md",
            "spec/login/design.md",
        ]
        result = check_spec_files(files)
        assert result.ok

    def test_only_tasks_file_is_ignored_and_fails(self):
        files = [
            "spec/login/tasks.md",
        ]
        result = check_spec_files(files)
        assert not result.ok
        assert "spec 문서 변경이 없습니다" in result.message

    def test_multiple_features_all_pass(self):
        files = [
            "spec/login/requirements.md",
            "spec/payment/design.md",
        ]
        result = check_spec_files(files)
        assert result.ok
        assert "login" in result.message
        assert "payment" in result.message

    def test_tasks_only_in_other_feature_does_not_block(self):
        files = [
            "spec/login/requirements.md",
            "spec/payment/tasks.md",
        ]
        result = check_spec_files(files)
        assert result.ok
        assert "login" in result.message

    def test_non_required_spec_files_ignored(self):
        files = [
            "spec/login/notes.md",
            "spec/login/diagram.png",
        ]
        result = check_spec_files(files)
        assert not result.ok
        assert "spec 문서 변경이 없습니다" in result.message

    def test_nested_spec_paths_handled(self):
        files = [
            "spec/login/requirements.md",
            "spec/login/sub/extra.md",
        ]
        result = check_spec_files(files)
        assert result.ok

    def test_spec_at_wrong_depth_ignored(self):
        files = ["spec/requirements.md"]
        result = check_spec_files(files)
        assert not result.ok
