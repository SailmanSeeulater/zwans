from views import render_results


def test_render_middle_page() -> None:
    results = [f"result {n}" for n in range(1, 10)]

    text = render_results(results, 2, per_page=3)

    assert text.splitlines() == [
        "- result 4",
        "- result 5",
        "- result 6",
        "",
        "< page 1 | Page 2 of 3 | page 3 >",
    ]


def test_render_empty() -> None:
    assert render_results([], 1).endswith("Page 1 of 1")
