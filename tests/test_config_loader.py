from src.review.config_loader import load_config_from_yaml, DEFAULT_CONFIG
from src.models.config import ReviewConfig


class TestLoadConfig:
    def test_default_config(self):
        assert isinstance(DEFAULT_CONFIG, ReviewConfig)
        assert DEFAULT_CONFIG.model is None
        assert DEFAULT_CONFIG.ignore.files == []

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
