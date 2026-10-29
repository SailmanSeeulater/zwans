def word_count(text: str) -> int:
    return len(text.split())


def is_palindrome(text: str) -> bool:
    letters = [c.lower() for c in text if c.isalnum()]
    return letters == letters[::-1]
