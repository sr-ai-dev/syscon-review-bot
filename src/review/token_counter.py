import tiktoken

_ENC = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    if not text:
        return 0
    return len(_ENC.encode(text))


def truncate_tokens(text: str, max_tokens: int) -> str:
    if max_tokens < 0:
        raise ValueError("max_tokens must be non-negative")
    encoded = _ENC.encode(text)
    if len(encoded) <= max_tokens:
        return text
    return _ENC.decode(encoded[:max_tokens])
