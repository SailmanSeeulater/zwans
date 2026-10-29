from text import is_palindrome


def test_palindromes():
    assert is_palindrome("A man, a plan, a canal: Panama")
    assert is_palindrome("racecar")
    assert not is_palindrome("hello")
