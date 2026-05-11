from src.review.rules.loader import load_config_from_yaml, DEFAULT_CONFIG
from src.models.config import ReviewConfig


class TestLoadConfig:
    def test_default_config(self):
        assert isinstance(DEFAULT_CONFIG, ReviewConfig)
        assert DEFAULT_CONFIG.rules.security is True

    def test_load_yaml_full(self):
        yaml_content = """
review:
  language: english
  severity_threshold: high
  model: gpt-5.4-mini

rules:
  architecture: true
  security: true
  code_quality: false

custom_rules:
  - "All endpoints must have auth middleware"

ignore:
  files:
    - "*.lock"
  extensions:
    - ".md"

approve_criteria:
  max_high_issues: 0
  max_medium_issues: 5
"""
        config = load_config_from_yaml(yaml_content)
        assert config.review_language == "english"
        assert config.model == "gpt-5.4-mini"
        assert config.rules.code_quality is False
        assert config.rules.security is True
        assert "All endpoints must have auth middleware" in config.custom_rules
        assert "*.lock" in config.ignore.files
        assert config.approve_criteria.max_medium_issues == 5

    def test_partial_yaml_uses_defaults(self):
        yaml_content = """
rules:
  security: false
"""
        config = load_config_from_yaml(yaml_content)
        assert config.rules.security is False
        assert config.rules.code_quality is True  # default

    def test_empty_yaml_returns_default(self):
        config = load_config_from_yaml("")
        assert config == DEFAULT_CONFIG
