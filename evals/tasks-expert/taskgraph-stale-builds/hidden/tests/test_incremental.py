"""Random edit sequences on a sample project: after every build, exactly the tasks the
README says must run have run, the files match a reference build, and they match what a
build from scratch gives."""

import random

import oracle
import pytest
import sample

from taskgraph import Builder, MemoryFS, Project, Task

STATE_PREFIX = ".taskgraph/"


def project_of(specs: list[oracle.Spec]) -> Project:
    project = Project()
    for spec in specs:
        project.add(Task(spec.name, spec.action, list(spec.inputs), list(spec.outputs),
                         dict(spec.params), spec.version))
    return project


def visible(fs: MemoryFS) -> dict[str, str]:
    return {p: t for p, t in fs.snapshot().items() if not p.startswith(STATE_PREFIX)}


class World:
    """The file system under test and the reference's copy, edited in step."""

    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)
        self.sample = sample.Sample(self.rng)
        self.fs = MemoryFS()
        self.files: dict[str, str] = {}
        self.history: dict[str, list[tuple[str, int]]] = {}
        self.reference = oracle.Reference()
        for path, text in sample.initial_files(self.rng).items():
            self.write(path, text)

    def write(self, path: str, text: str, mtime: int | None = None) -> None:
        self.fs.write(path, text, mtime=mtime)
        self.files[path] = text
        self.history.setdefault(path, []).append((text, self.fs.mtime(path)))

    def delete(self, path: str) -> None:
        if path in self.files:
            self.fs.delete(path)
            del self.files[path]

    def edit(self) -> str:
        """Make one random edit; a description of it."""
        rng = self.rng
        roll = rng.random()
        source = f"src/{rng.choice(sample.SOURCES)}.c"
        header = f"include/{rng.choice(sample.HEADERS)}"
        outputs = [p for spec in self.sample.specs() for p in spec.outputs if p in self.files]
        if roll < 0.14:
            self.write(source, sample.source_text(rng, source[4:6]))
            return f"rewrote {source}"
        if roll < 0.24:
            lines = self.files[source].splitlines()
            lines.insert(rng.randint(0, len(lines)), f"// comment {rng.randint(0, 9)}")
            self.write(source, "\n".join(lines) + "\n")
            return f"added a comment to {source}"
        if roll < 0.34:
            lines = self.files[source].splitlines()
            rng.shuffle(lines)
            self.write(source, "\n".join(lines) + "\n")
            return f"shuffled the lines of {source}"
        if roll < 0.44:
            path = header if rng.random() < 0.7 else "include/local/" + header.split("/")[1]
            if path in self.files and rng.random() < 0.3:
                self.delete(path)
                return f"deleted {path}"
            self.write(path, sample.header_text(rng, path.rsplit("/", 1)[1]))
            return f"wrote {path}"
        if roll < 0.5:
            path = rng.choice(sorted(self.files))
            self.fs.touch(path)
            return f"touched {path}"
        if roll < 0.56:
            path = rng.choice(sorted(self.files))
            self.write(path, self.files[path])
            return f"rewrote {path} unchanged"
        if roll < 0.64:
            path = rng.choice(sorted(p for p in self.history if p in self.files))
            text, mtime = rng.choice(self.history[path])
            self.write(path, text, mtime=mtime)
            return f"restored an old {path} with its old mtime {mtime}"
        if roll < 0.7:
            name = rng.choice(sample.SOURCES)
            if rng.random() < 0.5:
                self.sample.opt[name] = (self.sample.opt[name] + 1) % 3
                return f"changed opt of cc-{name}"
            self.sample.version[name] += 1
            return f"bumped the version of cc-{name}"
        if roll < 0.74:
            self.sample.title = rng.choice(["Manual", "Guide"])
            return f"set the docs title to {self.sample.title}"
        if roll < 0.8:
            path = "docs/footer.md"
            if path in self.files:
                self.delete(path)
                return "deleted the footer"
            self.write(path, f"v{rng.randint(1, 3)}\n")
            return "wrote a footer"
        if roll < 0.87 and outputs:
            path = rng.choice(outputs)
            if rng.random() < 0.5:
                self.delete(path)
                return f"deleted output {path}"
            self.write(path, "junk\n")
            return f"overwrote output {path}"
        if roll < 0.94:
            lines = self.files[source].splitlines()
            if any("#error" in line for line in lines):
                lines = [line for line in lines if "#error" not in line]
                self.write(source, "\n".join(lines) + "\n")
                return f"removed the #error from {source}"
            lines.append("#error not yet")
            self.write(source, "\n".join(lines) + "\n")
            return f"added an #error to {source}"
        return "nothing"

    def build(self) -> tuple:
        specs = self.sample.specs()
        result = Builder(project_of(specs), self.fs).build()
        want = self.reference.build(specs, self.files)
        return result, want


@pytest.mark.parametrize("seed", range(80))
def test_random_edits_rebuild_exactly_what_changed(seed: int) -> None:
    world = World(seed)
    done = []
    for step in range(14):
        if step:
            done.append(", ".join(world.edit() for _ in range(world.rng.randint(1, 2))))
        result, (ran, failed, blocked) = world.build()
        where = f"seed {seed}, build {step}, after: {done}"
        assert set(result.ran) == ran, (
            f"{where}\nran {sorted(result.ran)}\nshould have run exactly {sorted(ran)}"
        )
        assert set(result.failed) == failed, f"{where}: failed {result.failed}"
        assert set(result.blocked) == blocked, f"{where}: blocked {result.blocked}"
        assert visible(world.fs) == world.files, f"{where}: the files differ"
        if not failed and step % 3 == 2:
            sources = {p: t for p, t in world.files.items()
                       if p.startswith(("src/", "include/", "docs/"))}
            scratch = MemoryFS(sources)
            fresh = Builder(project_of(world.sample.specs()), scratch).build()
            assert fresh.ok
            assert visible(scratch) == visible(world.fs), f"{where}: differs from scratch"
