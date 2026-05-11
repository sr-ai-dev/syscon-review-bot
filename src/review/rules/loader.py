import logging

import yaml

from src.models.config import (
    ApprovalCriteria,
    IgnoreConfig,
    ReviewConfig,
    RulesConfig,
)


logger = logging.getLogger(__name__)

DEFAULT_CONFIG = ReviewConfig()


def load_config_from_yaml(yaml_content: str) -> ReviewConfig:
    if not yaml_content or not yaml_content.strip():
        return DEFAULT_CONFIG

    data = yaml.safe_load(yaml_content)
    if not data:
        logger.warning("Config YAML parses to empty/None — using defaults")
        return DEFAULT_CONFIG

    review_section = data.get("review", {})
    rules_section = data.get("rules", {})
    ignore_section = data.get("ignore", {})
    approve_section = data.get("approve_criteria", {})
    custom_rules = data.get("custom_rules", [])

    return ReviewConfig(
        review_language=review_section.get("language", DEFAULT_CONFIG.review_language),
        severity_threshold=review_section.get("severity_threshold", DEFAULT_CONFIG.severity_threshold),
        model=review_section.get("model"),
        rules=RulesConfig(**{**DEFAULT_CONFIG.rules.model_dump(), **rules_section}),
        custom_rules=custom_rules,
        ignore=IgnoreConfig(**{**DEFAULT_CONFIG.ignore.model_dump(), **ignore_section}),
        approve_criteria=ApprovalCriteria(**{**DEFAULT_CONFIG.approve_criteria.model_dump(), **approve_section}),
    )
