"""A reference follower over its own model of files, written from the README and sharing no
code with logtail: at each poll it works out from the files' whole contents which lines a
follower must deliver."""


class Files:
    """Paths naming inodes, inodes holding text: the same operations as FakeFS."""

    def __init__(self) -> None:
        self.paths: dict[str, int] = {}
        self.data: dict[int, str] = {}
        self.next = 0

    def new(self) -> int:
        self.next += 1
        self.data[self.next] = ""
        return self.next

    def create(self, path: str) -> None:
        self.paths[path] = self.new()

    def open_for_append(self, path: str) -> int:
        if path not in self.paths:
            self.paths[path] = self.new()
        return self.paths[path]

    def write(self, inode: int, text: str) -> None:
        self.data[inode] += text

    def rename(self, source: str, target: str) -> None:
        self.paths[target] = self.paths.pop(source)

    def unlink(self, path: str) -> None:
        del self.paths[path]

    def truncate(self, path: str, size: int = 0) -> None:
        inode = self.paths[path]
        self.data[inode] = self.data[inode][:size]

    def copy(self, source: str, target: str) -> None:
        inode = self.new()
        self.data[inode] = self.data[self.paths[source]]
        self.paths[target] = inode


class Reference:
    def __init__(self, files: Files, path: str, max_line: int, from_end: bool = False) -> None:
        self.files = files
        self.path = path
        self.max_line = max_line
        self.inode = files.paths.get(path)
        self.position = 0
        self.held = ""
        self.chars = 0  # characters a follower has to read to get here
        if self.inode is not None and from_end:
            self.position = len(files.data[self.inode])

    def poll(self) -> list[str]:
        out: list[str] = []
        current = self.files.paths.get(self.path)
        if self.inode is None:
            if current is None:
                return out
            self.inode, self.position, self.held = current, 0, ""
        elif current is not None and current != self.inode:
            self.read_rest(out)
            if self.held:
                out.append(self.held)
            self.inode, self.position, self.held = current, 0, ""
        self.read_rest(out)
        return out

    def read_rest(self, out: list[str]) -> None:
        text = self.files.data[self.inode]
        if len(text) < self.position:
            if self.held:
                out.append(self.held)
            self.held = ""
            self.position = 0
        new = text[self.position:]
        self.chars += len(new)
        self.position = len(text)
        pending = self.held + new
        *complete, partial = pending.split("\n")
        for line in complete:
            out += self.pieces(line)
        while len(partial) > self.max_line:
            out.append(partial[: self.max_line])
            partial = partial[self.max_line:]
        self.held = partial

    def pieces(self, line: str) -> list[str]:
        if len(line) <= self.max_line:
            return [line]
        cut = [line[i : i + self.max_line] for i in range(0, len(line), self.max_line)]
        return cut
