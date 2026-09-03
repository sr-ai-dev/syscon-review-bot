from enum import Enum


class ReviewInfraCategory(str, Enum):
    GITHUB_TRANSPORT_ERROR = "GITHUB_TRANSPORT_ERROR"
    GITHUB_RESPONSE_ERROR = "GITHUB_RESPONSE_ERROR"
    OPENAI_TRANSPORT_ERROR = "OPENAI_TRANSPORT_ERROR"
    OPENAI_RESPONSE_INCOMPLETE = "OPENAI_RESPONSE_INCOMPLETE"
    RESPONSE_SCHEMA_ERROR = "RESPONSE_SCHEMA_ERROR"


class ReviewInfraError(RuntimeError):
    """Safe, typed failure at the AI review infrastructure boundary."""

    def __init__(self, category: ReviewInfraCategory, message: str):
        self.category = category
        self.safe_message = message
        super().__init__(f"{category.value}: {message}")
