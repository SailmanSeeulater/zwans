from settings import load


def test_true_false():
    assert load({"a": "true", "b": "False"}) == {"a": True, "b": False}


def test_yes_no():
    assert load({"a": "yes", "b": "NO", "c": "maybe"}) == {"a": True, "b": False, "c": "maybe"}
