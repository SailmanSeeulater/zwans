from calc import average


def test_average_of_one_number() -> None:
    assert average([5]) == 5


def test_average_with_a_fraction() -> None:
    assert average([1, 2]) == 1.5
