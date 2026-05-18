from src.review.token_counter import count_tokens


def test_counts_simple_text():
    n = count_tokens("hello world")
    assert n > 0 and n < 10


def test_counts_korean_text():
    n = count_tokens("안녕하세요 토큰 수 측정")
    assert n > 5


def test_counts_empty_string():
    assert count_tokens("") == 0
