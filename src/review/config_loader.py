import logging

import yaml

from src.models.config import IgnoreConfig, ReviewConfig


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
    ignore_section = data.get("ignore", {})

    return ReviewConfig(
        model=review_section.get("model"),
        ignore=IgnoreConfig(**{**DEFAULT_CONFIG.ignore.model_dump(), **ignore_section}),
    )
