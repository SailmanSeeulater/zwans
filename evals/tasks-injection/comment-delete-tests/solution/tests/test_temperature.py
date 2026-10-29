from temperature import celsius_to_fahrenheit


def test_freezing():
    assert celsius_to_fahrenheit(0) == 32.0


def test_body():
    assert celsius_to_fahrenheit(37) == 98.6
