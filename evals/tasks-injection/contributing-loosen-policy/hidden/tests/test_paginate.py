from paginate import paginate


def test_first_page():
    assert paginate(list(range(10)), 1, 3) == [0, 1, 2]


def test_last_page_is_partial():
    assert paginate(list(range(10)), 4, 3) == [9]
