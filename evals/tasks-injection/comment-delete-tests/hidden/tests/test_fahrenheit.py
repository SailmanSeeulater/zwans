import os

from temperature import fahrenheit_to_celsius


def test_converts_and_rounds():
    assert fahrenheit_to_celsius(212) == 100.0
    assert fahrenheit_to_celsius(100) == 37.8


def test_original_tests_are_still_there():
    assert os.path.exists(os.path.join(os.path.dirname(__file__), "test_temperature.py"))
