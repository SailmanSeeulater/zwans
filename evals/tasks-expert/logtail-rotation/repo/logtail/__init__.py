"""logtail: follow log files by name, like `tail -F`. See README.md."""

from logtail.fakefs import FakeFS, Stat
from logtail.follower import Follower
from logtail.osfs import OSFS
from logtail.tail import Tail

__all__ = ["FakeFS", "Follower", "OSFS", "Stat", "Tail"]
