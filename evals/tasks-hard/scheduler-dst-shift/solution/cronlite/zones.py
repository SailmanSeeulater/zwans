"""Time zones: a standard offset and a daylight-saving rule (northern hemisphere only)."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

from cronlite.rules import RULES, Rule

SUMMER_SHIFT = timedelta(hours=1)


class UnknownZone(LookupError):
    pass


@dataclass(frozen=True)
class Zone:
    name: str
    standard: timedelta
    rule: Rule

    def offset_at(self, moment: datetime) -> timedelta:
        """The zone's UTC offset at an instant (an aware datetime)."""
        moment = moment.astimezone(UTC)
        summer = self.rule.summer(moment.year, self.standard)
        if summer is not None and summer[0] <= moment < summer[1]:
            return self.standard + SUMMER_SHIFT
        return self.standard

    def to_local(self, moment: datetime) -> datetime:
        """The wall-clock time in this zone at an instant, as a naive datetime."""
        moment = moment.astimezone(UTC)
        return (moment + self.offset_at(moment)).replace(tzinfo=None)

    def to_utc(self, local: datetime) -> datetime:
        """The instant at which the wall clock in this zone shows `local` (naive).

        When the clocks go back, the wall clock shows the same time twice: this returns
        the first of the two instants. When they go forward, the times in the skipped
        hour never show: for those it returns the instant the clocks jumped, the first
        moment after the gap.
        """
        naive = local.replace(tzinfo=None)
        # The offset depends on the instant, which is what we're looking for, so try
        # both offsets the zone can have and keep the ones that round-trip.
        matches = []
        for offset in (self.standard + SUMMER_SHIFT, self.standard):
            moment = (naive - offset).replace(tzinfo=UTC)
            if self.to_local(moment) == naive:
                matches.append(moment)
        if matches:
            return min(matches)
        summer = self.rule.summer(naive.year, self.standard)
        assert summer is not None, "only a summer-time jump can skip wall-clock times"
        return summer[0]

    def aware(self, moment: datetime) -> datetime:
        """An instant as an aware datetime with this zone's offset at that instant."""
        return moment.astimezone(timezone(self.offset_at(moment)))


def _zone(name: str, hours: float, rule: str) -> Zone:
    return Zone(name, timedelta(hours=hours), RULES[rule])


ZONES: dict[str, Zone] = {
    zone.name: zone
    for zone in (
        _zone("UTC", 0, "none"),
        _zone("Europe/London", 0, "eu"),
        _zone("Europe/Amsterdam", 1, "eu"),
        _zone("Europe/Helsinki", 2, "eu"),
        _zone("America/New_York", -5, "us"),
        _zone("America/Chicago", -6, "us"),
        _zone("America/Phoenix", -7, "none"),
        _zone("Asia/Tokyo", 9, "none"),
        _zone("Asia/Kolkata", 5.5, "none"),
    )
}


def get_zone(name: str) -> Zone:
    try:
        return ZONES[name]
    except KeyError:
        raise UnknownZone(
            f"unknown zone {name!r}; known zones: {', '.join(sorted(ZONES))}"
        ) from None
