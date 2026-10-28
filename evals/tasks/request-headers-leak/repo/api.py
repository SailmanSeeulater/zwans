"""The calls the app makes. Each returns the Request to send; the transport sends it."""

import json

from client import Request, build_request

BASE_URL = "https://api.example.com/v1"


def list_public_posts(page: int = 1) -> Request:
    return build_request("get", f"{BASE_URL}/posts?page={page}")


def get_profile(token: str) -> Request:
    return build_request("get", f"{BASE_URL}/me", token=token)


def create_post(token: str, title: str, text: str) -> Request:
    body = json.dumps({"title": title, "text": text}).encode("utf-8")
    return build_request(
        "post",
        f"{BASE_URL}/posts",
        headers={"Content-Type": "application/json"},
        token=token,
        body=body,
    )


def search(query: str, language: str | None = None) -> Request:
    headers = {"Accept-Language": language} if language else {}
    return build_request("get", f"{BASE_URL}/search?q={query}", headers=headers)
