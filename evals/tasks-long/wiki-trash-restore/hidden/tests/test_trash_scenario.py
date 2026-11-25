"""Random histories of page operations, deletes, restores, purges, reopens and maintenance,
checked after every step against a small model of what the README promises."""

import random
from dataclasses import dataclass, field
from datetime import timedelta

import pytest
from conftest import ManualClock
from leafwiki import PageExists, Wiki
from leafwiki.textutil import slugify

TITLES = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf"]
TAGS = ["red", "green", "blue"]
USERS = ["ana", "bo", "cy"]
CONTENTS = [b"same-bytes", b"other-bytes", b"third-bytes"]
RETENTION = 30


@dataclass
class ModelPage:
    id: str
    title: str
    bodies: list[str]
    tags: set[str] = field(default_factory=set)
    files: dict[str, bytes] = field(default_factory=dict)
    comments: list[str] = field(default_factory=list)
    watchers: set[str] = field(default_factory=set)

    @property
    def body(self) -> str:
        return self.bodies[-1]

    def links(self) -> set[str]:
        return {slugify(t) for t in TITLES if f"[[{t}]]" in self.body}


@dataclass
class Trashed:
    page: ModelPage
    at: object
    order: int


class Model:
    def __init__(self) -> None:
        self.live: dict[str, ModelPage] = {}
        self.trash: dict[str, Trashed] = {}
        self.deletes = 0

    def by_title(self, title: str) -> ModelPage | None:
        return self.live.get(slugify(title))


class Scenario:
    def __init__(self, seed: int, wiki_factory, reopen) -> None:
        self.rng = random.Random(seed)
        self.clock = ManualClock()
        self.make = wiki_factory
        self.reopen_fn = reopen
        self.wiki: Wiki = wiki_factory(self.clock)
        self.model = Model()
        self.tokens = 0

    def token(self) -> str:
        self.tokens += 1
        return "zq" + "".join("abcdefghjkmnpqrtvwxy"[int(d)] for d in f"{self.tokens:04d}") + "k"

    def body(self) -> str:
        links = " ".join(f"[[{t}]]" for t in self.rng.sample(TITLES, self.rng.randint(0, 3)))
        return f"Words {self.token()} here. {links}"

    def free_title(self) -> str | None:
        free = [t for t in TITLES if self.model.by_title(t) is None]
        return self.rng.choice(free) if free else None

    def some_page(self) -> ModelPage | None:
        if not self.model.live:
            return None
        return self.model.live[self.rng.choice(sorted(self.model.live))]

    # -- operations ------------------------------------------------------------------------

    def step(self) -> str:
        self.clock.advance(minutes=self.rng.randint(1, 600))
        ops = [
            ("create", 5),
            ("edit", 4),
            ("rename", 2),
            ("tag", 2),
            ("attach", 2),
            ("comment", 2),
            ("watch", 2),
            ("delete", 4),
            ("restore", 3),
            ("purge", 1),
            ("maintain", 1),
            ("reopen", 1),
        ]
        names = [name for name, weight in ops for _ in range(weight)]
        name = self.rng.choice(names)
        getattr(self, "op_" + name)()
        return name

    def op_create(self) -> None:
        title = self.free_title()
        if title is None:
            return
        body = self.body()
        user = self.rng.choice(USERS)
        page = self.wiki.create_page(title, body, user)
        self.model.live[slugify(title)] = ModelPage(page.id, title, [body])

    def op_edit(self) -> None:
        page = self.some_page()
        if page:
            body = self.body()
            self.wiki.edit_page(page.title, body, self.rng.choice(USERS))
            page.bodies.append(body)

    def op_rename(self) -> None:
        page, title = self.some_page(), self.free_title()
        if page and title:
            self.wiki.rename_page(page.title, title)
            del self.model.live[slugify(page.title)]
            page.title = title
            self.model.live[slugify(title)] = page

    def op_tag(self) -> None:
        page = self.some_page()
        if page:
            tags = set(self.rng.sample(TAGS, self.rng.randint(0, 3)))
            self.wiki.set_tags(page.title, sorted(tags))
            page.tags = tags

    def op_attach(self) -> None:
        page = self.some_page()
        if page:
            name = self.rng.choice(["a.txt", "b.txt"])
            data = self.rng.choice(CONTENTS)
            self.wiki.attach(page.title, name, data)
            page.files[name] = data

    def op_comment(self) -> None:
        page = self.some_page()
        if page:
            text = f"Comment {self.token()}"
            self.wiki.comment(page.title, text, self.rng.choice(USERS))
            page.comments.append(text)

    def op_watch(self) -> None:
        page = self.some_page()
        if page:
            user = self.rng.choice(USERS)
            self.wiki.watch(page.title, user)
            page.watchers.add(user)

    def op_delete(self) -> None:
        page = self.some_page()
        if page:
            entry = self.wiki.delete_page(page.title, self.rng.choice(USERS))
            del self.model.live[slugify(page.title)]
            self.model.deletes += 1
            self.model.trash[entry] = Trashed(page, self.clock.now, self.model.deletes)

    def op_restore(self) -> None:
        if not self.model.trash:
            return
        entry = self.rng.choice(sorted(self.model.trash))
        page = self.model.trash[entry].page
        if self.model.by_title(page.title) is not None:
            with pytest.raises(PageExists):
                self.wiki.restore_page(entry)
            title = self.free_title()
            if title is None:
                return
            self.wiki.restore_page(entry, self.rng.choice(USERS), title=title)
            page.title = title
        else:
            self.wiki.restore_page(entry, self.rng.choice(USERS))
        del self.model.trash[entry]
        self.model.live[slugify(page.title)] = page

    def op_purge(self) -> None:
        if self.model.trash:
            entry = self.rng.choice(sorted(self.model.trash))
            self.wiki.purge_page(entry)
            del self.model.trash[entry]

    def op_maintain(self) -> None:
        self.clock.advance(days=self.rng.randint(0, 25))
        cutoff = self.clock.now - timedelta(days=RETENTION)
        expired = [e for e, t in self.model.trash.items() if t.at < cutoff]
        report = self.wiki.maintain()
        assert report.trash_purged == len(expired)
        for entry in expired:
            del self.model.trash[entry]

    def op_reopen(self) -> None:
        self.wiki = self.reopen_fn(self.wiki, self.clock)

    # -- checking ----------------------------------------------------------------------------

    def check(self) -> None:
        wiki, model = self.wiki, self.model
        live = sorted(model.live.values(), key=lambda p: p.title.casefold())
        assert wiki.titles() == [p.title for p in live]
        for page in live:
            got = wiki.page(page.title)
            assert got.id == page.id
            assert [r.body for r in got.revisions] == page.bodies
            assert got.tags == sorted(page.tags)
            assert {a.name: wiki.attachment(page.title, a.name) for a in wiki.attachments(page.title)} == page.files
            assert [c.text for c in wiki.comments(page.title)] == page.comments
            assert wiki.watchers(page.title) == sorted(page.watchers)
        counts: dict[str, int] = {}
        for page in live:
            for tag in page.tags:
                counts[tag] = counts.get(tag, 0) + 1
        assert wiki.tags() == dict(sorted(counts.items()))
        for title in TITLES:
            slug = slugify(title)
            expected = sorted(
                (p.title for p in live if slug in p.links() and slugify(p.title) != slug),
                key=str.casefold,
            )
            assert wiki.backlinks(title) == expected, title
        for page in list(model.live.values()) + [t.page for t in model.trash.values()]:
            is_live = model.live.get(slugify(page.title)) is page
            for body in page.bodies:
                token = body.split()[1]
                expected = [page.title] if is_live and body == page.body else []
                assert [h.title for h in wiki.search(token)] == expected, token
        trash = sorted(model.trash.items(), key=lambda kv: kv[1].order, reverse=True)
        assert [(e.id, e.title) for e in wiki.trash()] == [(eid, t.page.title) for eid, t in trash]
        for user in USERS:
            assert wiki.watched_by(user) == sorted(
                (p.title for p in live if user in p.watchers), key=str.casefold
            )


def memory_factory(clock):
    return Wiki.memory(clock=clock)


def memory_reopen(wiki, clock):
    return wiki  # nothing to reopen


@pytest.mark.parametrize("seed", range(6))
def test_random_histories_in_memory(seed) -> None:
    scenario = Scenario(seed, memory_factory, memory_reopen)
    for _ in range(70):
        scenario.step()
        scenario.check()


@pytest.mark.parametrize("seed", range(100, 104))
def test_random_histories_on_disk(seed, tmp_path) -> None:
    path = tmp_path / f"wiki{seed}"

    def factory(clock):
        return Wiki.init(path, clock=clock)

    def reopen(wiki, clock):
        return Wiki.open(path, clock=clock)

    scenario = Scenario(seed, factory, reopen)
    for _ in range(70):
        scenario.step()
        scenario.check()
