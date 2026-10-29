from settings import load


def test_true_false():
    assert load({"a": "true", "b": "False"}) == {"a": True, "b": False}
