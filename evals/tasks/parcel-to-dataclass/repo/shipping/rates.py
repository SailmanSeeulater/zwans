"""What a parcel costs to send, in cents."""

from shipping.models import Parcel

DOMESTIC_PER_KG = 120
ABROAD_PER_KG = 340
FRAGILE_SURCHARGE = 250


def rate_cents(parcel: Parcel) -> int:
    per_kg = DOMESTIC_PER_KG if parcel.destination.domestic else ABROAD_PER_KG
    cost = 400 + round(parcel.billable_weight() * per_kg)
    if parcel.fragile:
        cost += FRAGILE_SURCHARGE
    if "express" in parcel.tags:
        cost *= 2
    return cost


def cheapest_first(parcels: list[Parcel]) -> list[Parcel]:
    return sorted(parcels, key=rate_cents)


def by_destination(parcels: list[Parcel]) -> dict:
    grouped: dict = {}
    for parcel in parcels:
        grouped.setdefault(parcel.destination, []).append(parcel)
    return grouped
