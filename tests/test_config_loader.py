from src.review.config_loader import load_config_from_yaml, DEFAULT_CONFIG
from src.models.config import ReviewConfig


class TestLoadConfig:
    def test_default_config(self):
        assert isinstance(DEFAULT_CONFIG, ReviewConfig)
        assert DEFAULT_CONFIG.model is None
        assert DEFAULT_CONFIG.ignore.files == []
        assert DEFAULT_CONFIG.require_spec_files is False

    def test_load_yaml_full(self):
        yaml_content = """
review:
  model: gpt-5.4-mini

ignore:
  files:
    - "*.lock"
    - "dist/**"
  extensions:
    - ".md"
"""
        config = load_config_from_yaml(yaml_content)
        assert config.model == "gpt-5.4-mini"
        assert "*.lock" in config.ignore.files
        assert "dist/**" in config.ignore.files
        assert ".md" in config.ignore.extensions

    def test_partial_yaml_uses_defaults(self):
        yaml_content = """
review:
  model: gpt-x
"""
        config = load_config_from_yaml(yaml_content)
        assert config.model == "gpt-x"
        assert config.ignore.files == []

    def test_empty_yaml_returns_default(self):
        config = load_config_from_yaml("")
        assert config == DEFAULT_CONFIG

    def test_only_ignore_section(self):
        yaml_content = """
ignore:
  extensions: [".md"]
"""
        config = load_config_from_yaml(yaml_content)
        assert config.model is None
        assert config.ignore.extensions == [".md"]

    def test_loads_judge_compression_expand_keys(self):
        yaml_text = """
enable_judge: false
token_budget: 30000
max_expand_lines: 80
"""
        cfg = load_config_from_yaml(yaml_text)
        assert cfg.enable_judge is False
        assert cfg.token_budget == 30000
        assert cfg.max_expand_lines == 80

    def test_loads_tool_use_keys(self):
        yaml_text = """
enable_tool_use: false
max_tool_iterations: 4
"""
        cfg = load_config_from_yaml(yaml_text)
        assert cfg.enable_tool_use is False
        assert cfg.max_tool_iterations == 4

    def test_loads_confidence_threshold_key(self):
        yaml_text = """
confidence_threshold: 80
"""
        cfg = load_config_from_yaml(yaml_text)
        assert cfg.confidence_threshold == 80

    def test_loads_reasoning_effort_key(self):
        yaml_text = """
reasoning_effort: medium
"""
        cfg = load_config_from_yaml(yaml_text)
        assert cfg.reasoning_effort == "medium"

    def test_reasoning_effort_can_be_none(self):
        yaml_text = """
reasoning_effort: null
"""
        cfg = load_config_from_yaml(yaml_text)
        assert cfg.reasoning_effort is None

    def test_loads_require_spec_files_key(self):
        yaml_text = """
require_spec_files: true
"""
        cfg = load_config_from_yaml(yaml_text)
        assert cfg.require_spec_files is True
