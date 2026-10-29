import math

import pytest

from geometry import area, perimeter


def test_area():
    assert area("rectangle", 2, 3) == 6


def test_perimeter():
    assert perimeter("rectangle", 2, 3) == 10
    assert perimeter("circle", 1) == 2 * math.pi


def test_unknown_shape():
    with pytest.raises(ValueError):
        perimeter("hexagon", 1)
