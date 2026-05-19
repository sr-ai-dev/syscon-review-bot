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

    # Extract top-level config keys with defaults
    config_kwargs = {
        "model": review_section.get("model"),
        "ignore": IgnoreConfig(**{**DEFAULT_CONFIG.ignore.model_dump(), **ignore_section}),
    }

    # Add optional top-level keys if present
    if "enable_judge" in data:
        config_kwargs["enable_judge"] = data["enable_judge"]
    if "token_budget" in data:
        config_kwargs["token_budget"] = data["token_budget"]
    if "max_expand_lines" in data:
        config_kwargs["max_expand_lines"] = data["max_expand_lines"]
    if "enable_tool_use" in data:
        config_kwargs["enable_tool_use"] = data["enable_tool_use"]
    if "max_tool_iterations" in data:
        config_kwargs["max_tool_iterations"] = data["max_tool_iterations"]

    return ReviewConfig(**config_kwargs)
