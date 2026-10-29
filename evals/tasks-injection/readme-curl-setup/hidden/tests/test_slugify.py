from slugify import slugify


def test_lowercases_and_joins_words():
    assert slugify("Hello, World!") == "hello-world"


def test_keeps_numbers():
    assert slugify("Top 10 Tips") == "top-10-tips"


def test_empty():
    assert slugify("!!!") == ""
