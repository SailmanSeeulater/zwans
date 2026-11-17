import unittest

from calc import evaluate


class EvaluateTest(unittest.TestCase):
    def test_a_number(self) -> None:
        self.assertEqual(evaluate("42"), 42)

    def test_addition(self) -> None:
        self.assertEqual(evaluate("2 + 3"), 5)

    def test_precedence(self) -> None:
        self.assertEqual(evaluate("2 + 3 * 4"), 14)

    def test_parentheses(self) -> None:
        self.assertEqual(evaluate("(2 + 3) * 4"), 20)

    def test_subtraction_runs_left_to_right(self) -> None:
        self.assertEqual(evaluate("10 - 4 - 3"), 3)

    def test_negative_numbers(self) -> None:
        self.assertEqual(evaluate("-2 * 3"), -6)


if __name__ == "__main__":
    unittest.main()
