"""A small C-like project for the tests: sources, headers found by a search path, docs,
and the tasks that turn them into objects, programs and a release note. The actions only
use the context API the README documents."""

import hashlib
import random
import re

from oracle import Spec

from taskgraph import TaskFailed

INCLUDE = re.compile(r'^#include "([^"]+)"$')
SEARCH = ["include/local", "include"]
HEADERS = [f"h{n}.h" for n in range(5)]
SOURCES = [f"c{n}" for n in range(4)]


def strip(ctx) -> None:
    (source,) = ctx.inputs
    text = ctx.read(source)
    if text is None:
        raise TaskFailed(f"no {source}")
    kept = [line for line in text.splitlines() if not line.startswith(ctx.params["marker"])]
    ctx.write(ctx.outputs[0], "\n".join(kept) + "\n")


def preprocess(ctx) -> None:
    (source,) = ctx.inputs
    text = ctx.read(source)
    if text is None:
        raise TaskFailed(f"no {source}")
    out: list[str] = []
    seen: set[str] = set()
    stack = [iter(text.splitlines())]
    while stack:
        line = next(stack[-1], None)
        if line is None:
            stack.pop()
            continue
        if line.startswith("//"):
            continue
        if "#error" in line:
            raise TaskFailed(line)
        match = INCLUDE.match(line)
        if not match:
            out.append(line)
            continue
        for directory in ctx.params["search"]:
            path = f"{directory}/{match.group(1)}"
            content = ctx.read(path)
            if content is not None:
                break
        else:
            raise TaskFailed(f"cannot find {match.group(1)}")
        if path not in seen:
            seen.add(path)
            stack.append(iter(content.splitlines()))
    ctx.write(ctx.outputs[0], "\n".join(out) + "\n")


def compile_(ctx) -> None:
    text = ctx.read(ctx.inputs[0])
    lines = [line for line in text.splitlines() if line.strip()]
    if ctx.params["opt"] >= 1:
        lines = sorted(set(lines))
    ctx.write(ctx.outputs[0], f"obj opt={ctx.params['opt']}\n" + "\n".join(lines) + "\n")


def link(ctx) -> None:
    parts = []
    for path in ctx.inputs:
        text = ctx.read(path)
        parts.append(f"{path} {hashlib.sha256(text.encode()).hexdigest()[:8]}")
    ctx.write(ctx.outputs[0], "\n".join(parts) + "\n")


def docs(ctx) -> None:
    body = ctx.read("docs/intro.md") or ""
    footer = ctx.read("docs/footer.md")
    page = f"<h1>{ctx.params['title']}</h1>\n{body}"
    if footer is not None:
        page += f"<footer>{footer}</footer>\n"
    ctx.write(ctx.outputs[0], page)


def release(ctx) -> None:
    lines = 0
    for path in ctx.inputs:
        lines += len(ctx.read(path).splitlines())
    ctx.write(ctx.outputs[0], f"{len(ctx.inputs)} parts, {lines // 4} blocks\n")


class Sample:
    """The project's settings (which can change between builds) and its tasks."""

    def __init__(self, rng: random.Random) -> None:
        self.opt = {source: rng.randint(0, 2) for source in SOURCES}
        self.version = {source: 1 for source in SOURCES}
        self.title = "Manual"
        self.apps = [
            sorted(rng.sample(SOURCES, rng.randint(1, 3))),
            sorted(rng.sample(SOURCES, rng.randint(1, 2))),
        ]

    def specs(self) -> list[Spec]:
        specs = []
        for source in SOURCES:
            specs.append(Spec(f"strip-{source}", strip, [f"src/{source}.c"],
                              [f"build/{source}.s"], {"marker": "//"}))
            specs.append(Spec(f"pp-{source}", preprocess, [f"build/{source}.s"],
                              [f"build/{source}.i"], {"search": SEARCH}))
            specs.append(Spec(f"cc-{source}", compile_, [f"build/{source}.i"],
                              [f"build/{source}.o"], {"opt": self.opt[source]},
                              self.version[source]))
        for number, members in enumerate(self.apps):
            specs.append(Spec(f"link-app{number}", link,
                              [f"build/{m}.o" for m in members], [f"bin/app{number}"]))
        specs.append(Spec("docs", docs, ["docs/intro.md"], ["build/docs.html"],
                          {"title": self.title}))
        specs.append(Spec("release", release, ["bin/app0", "bin/app1", "build/docs.html"],
                          ["dist/release.txt"]))
        return specs


def code_line(rng: random.Random, prefix: str) -> str:
    return f"int {prefix}_{rng.randint(0, 6)} = {rng.randint(0, 3)};"


def header_text(rng: random.Random, name: str) -> str:
    lines = [code_line(rng, name[:2]) for _ in range(rng.randint(1, 3))]
    if rng.random() < 0.4:
        lines.insert(0, f'#include "{rng.choice(HEADERS)}"')
    if rng.random() < 0.5:
        lines.append(f"// {name} note {rng.randint(0, 3)}")
    return "\n".join(lines) + "\n"


def source_text(rng: random.Random, name: str) -> str:
    lines = [f'#include "{h}"' for h in rng.sample(HEADERS, rng.randint(0, 2))]
    lines += [code_line(rng, name) for _ in range(rng.randint(1, 3))]
    for _ in range(rng.randint(0, 2)):
        lines.insert(rng.randint(0, len(lines)), f"// comment {rng.randint(0, 3)}")
    return "\n".join(lines) + "\n"


def initial_files(rng: random.Random) -> dict[str, str]:
    files = {f"include/{h}": header_text(rng, h) for h in HEADERS}
    files.update({f"src/{s}.c": source_text(rng, s) for s in SOURCES})
    files["docs/intro.md"] = "Hello.\n"
    return files
