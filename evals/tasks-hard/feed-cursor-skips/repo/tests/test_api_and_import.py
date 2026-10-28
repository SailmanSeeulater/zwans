import json

from feedsvc.api import Api
from feedsvc.importer import import_export


def test_publish_and_read_through_the_api(service) -> None:
    api = Api(service)
    assert api.handle("POST", "/users/ada/follow", json.dumps({"user": "grace"})) == (204, {})
    status, post = api.handle("POST", "/posts", json.dumps({"author": "grace", "body": "hi"}))
    assert status == 201 and post["body"] == "hi"

    status, feed = api.handle("GET", "/feed?user=ada&limit=5")

    assert status == 200
    assert [item["body"] for item in feed["items"]] == ["hi"]
    assert "next" not in feed and "top" in feed


def test_api_paging(service) -> None:
    api = Api(service)
    for n in range(7):
        service.publish("ada", f"p{n}")

    seen = []
    status, feed = api.handle("GET", "/users/ada/posts?limit=3")
    seen += [item["body"] for item in feed["items"]]
    while "next" in feed:
        assert len(seen) < 100, "paging never ends"
        status, feed = api.handle("GET", f"/users/ada/posts?limit=3&cursor={feed['next']}")
        seen += [item["body"] for item in feed["items"]]

    assert seen == [f"p{n}" for n in range(6, -1, -1)]


def test_api_errors(service) -> None:
    api = Api(service)
    assert api.handle("GET", "/feed")[0] == 400
    assert api.handle("GET", "/feed?user=ada&cursor=garbage")[0] == 400
    assert api.handle("GET", "/feed?user=ada&limit=x")[0] == 400
    assert api.handle("POST", "/posts", "not json")[0] == 400
    assert api.handle("GET", "/nope")[0] == 404


def test_api_refresh(service) -> None:
    api = Api(service)
    _, feed = api.handle("GET", "/feed?user=ada")
    service.publish("ada", "new")
    status, fresh = api.handle("GET", f"/feed/refresh?user=ada&since={feed['top']}")
    assert status == 200
    assert [item["body"] for item in fresh["items"]] == ["new"]


def test_import_uses_midnight_timestamps(service) -> None:
    export = {
        "author": "ada",
        "posts": [
            {"date": "2019-05-03", "text": "first"},
            {"date": "2019-05-04", "text": "second"},
            {"date": "someday", "text": "bad"},
            {"date": "2019-05-05", "text": ""},
        ],
    }

    report = import_export(service, export)

    assert report.imported == 2
    assert [index for index, _ in report.skipped] == [2, 3]
    assert [p.to_dict()["created_at"] for p in service.profile("ada").items] == [
        "2019-05-04T00:00:00Z",
        "2019-05-03T00:00:00Z",
    ]
