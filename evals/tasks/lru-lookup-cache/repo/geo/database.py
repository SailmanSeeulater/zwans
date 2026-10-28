"""The slow source of truth. In production this reads a large file from disk."""

import ipaddress
from dataclasses import dataclass


@dataclass(frozen=True)
class Location:
    country: str
    city: str


class AddressNotFound(LookupError):
    pass


class Database:
    def __init__(self, networks: dict[str, Location]) -> None:
        self._networks = [
            (ipaddress.ip_network(network), location) for network, location in networks.items()
        ]
        self.queries = 0

    def find(self, address: str) -> Location:
        self.queries += 1
        ip = ipaddress.ip_address(address)
        best = None
        for network, location in self._networks:
            if ip in network and (best is None or network.prefixlen > best[0].prefixlen):
                best = (network, location)
        if best is None:
            raise AddressNotFound(address)
        return best[1]
