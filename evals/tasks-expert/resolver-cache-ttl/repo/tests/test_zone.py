import pytest

from relaydns import BadName, Soa, Zone, ZoneError, normalize
from relaydns.zone import CNAME, NODATA, NXDOMAIN, RECORDS

ZONE = """
; a small zone
$SOA example. 3600 ns1.example. hostmaster.example. 7 120
www.example.     300  CNAME  web.example.
web.example.      60  A      192.0.2.10
web.example.      60  A      192.0.2.11
web.example.      60  TXT    "v=1 web"
mail.example.    600  MX     10 mx.example.
"""


def test_names_are_normalized() -> None:
    assert normalize("WWW.Example") == "www.example."
    assert normalize("www.example.") == "www.example."
    assert normalize(".") == "."
    with pytest.raises(BadName):
        normalize("a..b")
    with pytest.raises(BadName):
        normalize("bad name.example")


def test_parse_and_lookup() -> None:
    zone = Zone.parse(ZONE)

    assert Soa.of(zone.soa) == Soa("ns1.example.", "hostmaster.example.", 7, 120)
    reply = zone.lookup("web.example", "A")
    assert reply.kind == RECORDS
    assert [r.value for r in reply.records] == ["192.0.2.10", "192.0.2.11"]
    assert zone.lookup("mail.example.", "MX").records[0].value == "10 mx.example."
    assert zone.lookup("web.example.", "TXT").records[0].value == '"v=1 web"'


def test_aliases_and_negative_replies() -> None:
    zone = Zone.parse(ZONE)

    alias = zone.lookup("www.example.", "A")
    assert alias.kind == CNAME and alias.records[0].value == "web.example."
    assert zone.lookup("www.example.", "CNAME").kind == RECORDS
    nodata = zone.lookup("web.example.", "MX")
    assert nodata.kind == NODATA and nodata.soa == zone.soa
    assert zone.lookup("nope.example.", "A").kind == NXDOMAIN


def test_a_cname_cant_share_a_name() -> None:
    zone = Zone.parse(ZONE)
    with pytest.raises(ZoneError):
        zone.add("www.example.", 60, "A", "192.0.2.1")
    with pytest.raises(ZoneError):
        zone.add("web.example.", 60, "CNAME", "other.example.")


def test_replace() -> None:
    zone = Zone.parse(ZONE)

    zone.replace("web.example.", 30, "A", "192.0.2.99")
    zone.replace("www.example.", 45, "A", "192.0.2.1")

    assert [r.ttl for r in zone.lookup("web.example.", "A").records] == [30]
    assert zone.lookup("web.example.", "TXT").kind == RECORDS
    assert zone.lookup("www.example.", "A").records[0].value == "192.0.2.1"


@pytest.mark.parametrize(
    "text",
    ["www.example. 60 A", "www.example. sixty A 192.0.2.1", "$SOA example. 60 ns1.", "a. 60 SOA x"],
)
def test_bad_zone_files(text: str) -> None:
    with pytest.raises(ZoneError):
        Zone.parse(text)
