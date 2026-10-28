from shipping.models import Parcel


def label(parcel: Parcel) -> str:
    address = parcel.destination
    lines = [address.street, f"{address.postcode} {address.city}"]
    if not address.domestic:
        lines.append(address.country)
    if parcel.fragile:
        lines.append("FRAGILE")
    lines.extend(tag.upper() for tag in parcel.tags)
    return "\n".join(lines)
