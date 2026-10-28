"""Building a site: plan every output, then write the ones whose inputs changed."""

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from sitegen.cache import CACHE_NAME, BuildCache
from sitegen.config import Config, load_config
from sitegen.content import load_content
from sitegen.plan import Output, SitePlan, static_outputs
from sitegen.templates import Engine
from sitegen.theme import TEMPLATES


@dataclass
class BuildReport:
    written: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    def describe(self) -> str:
        return (
            f"wrote {len(self.written)}, unchanged {len(self.unchanged)}, "
            f"removed {len(self.removed)}"
        )


class Builder:
    """Builds one site. `sitegen serve` keeps a Builder around and calls build() again
    after every change; `sitegen build` makes a new one each time."""

    def __init__(self, root: Path, *, drafts: bool = False) -> None:
        self.root = Path(root)
        self.drafts = drafts
        self.config: Config = load_config(self.root)
        self.engine = Engine(self.config.templates_dir, TEMPLATES, self.config)

    def reload_config(self) -> None:
        self.config = load_config(self.root)
        self.engine.settings = self.config

    def plan(self) -> list[Output]:
        pages = load_content(self.config.content_dir, drafts=self.drafts)
        outputs = SitePlan(self.config, self.engine, pages).outputs()
        return outputs + static_outputs(self.config.static_dir)

    def build(self, *, clean: bool = False) -> BuildReport:
        self.reload_config()
        out_dir = self.config.output_dir
        if clean and out_dir.exists():
            shutil.rmtree(out_dir)
        outputs = self.plan()
        cache = BuildCache.load(out_dir)
        report = BuildReport()

        for output in outputs:
            target = out_dir / output.path
            if cache.is_fresh(output.path, output.signature) and target.is_file():
                report.unchanged.append(output.path)
                continue
            content = output.render()
            data = content.encode("utf-8") if isinstance(content, str) else content
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            cache.record(output.path, output.signature)
            report.written.append(output.path)

        produced = {output.path for output in outputs}
        for stale in sorted(cache.paths() - produced):
            self._remove(out_dir, stale)
            cache.forget(stale)
            report.removed.append(stale)

        cache.save()
        return report

    def _remove(self, out_dir: Path, relative: str) -> None:
        target = out_dir / relative
        if target.is_file():
            target.unlink()
        # Remove folders the file leaves empty, but never public/ itself.
        folder = target.parent
        while folder != out_dir and folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
            folder = folder.parent


def is_built(root: Path) -> bool:
    return (load_config(root).output_dir / CACHE_NAME).is_file()
