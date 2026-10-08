from calc import average, clamp


def test_average() -> None:
    assert average([2, 4, 6]) == 4


def test_clamp() -> None:
    assert clamp(15, 0, 10) == 10
    assert clamp(-5, 0, 10) == 0
