"""The two records everything else in shipping passes around."""


class Address:
    """Where a parcel goes. Immutable, so it can be used as a dict key."""

    def __init__(self, street: str, city: str, postcode: str, country: str = "NL") -> None:
        object.__setattr__(self, "street", street)
        object.__setattr__(self, "city", city)
        object.__setattr__(self, "postcode", postcode)
        object.__setattr__(self, "country", country)

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError(f"cannot assign to field {name!r}")

    def __delattr__(self, name: str) -> None:
        raise AttributeError(f"cannot delete field {name!r}")

    def __repr__(self) -> str:
        return (
            f"Address(street={self.street!r}, city={self.city!r}, "
            f"postcode={self.postcode!r}, country={self.country!r})"
        )

    def __eq__(self, other: object) -> bool:
        if other.__class__ is not self.__class__:
            return NotImplemented
        return (self.street, self.city, self.postcode, self.country) == (
            other.street,
            other.city,
            other.postcode,
            other.country,
        )

    def __hash__(self) -> int:
        return hash((self.street, self.city, self.postcode, self.country))

    @property
    def domestic(self) -> bool:
        return self.country == "NL"


class Parcel:
    """A box with its size in centimetres and weight in kilograms."""

    def __init__(
        self,
        weight_kg: float,
        length_cm: int,
        width_cm: int,
        height_cm: int,
        destination: Address,
        fragile: bool = False,
        tags: list[str] | None = None,
    ) -> None:
        if weight_kg <= 0:
            raise ValueError("weight must be positive")
        if min(length_cm, width_cm, height_cm) <= 0:
            raise ValueError("every side must be positive")
        self.weight_kg = weight_kg
        self.length_cm = length_cm
        self.width_cm = width_cm
        self.height_cm = height_cm
        self.destination = destination
        self.fragile = fragile
        self.tags = [] if tags is None else tags

    def __repr__(self) -> str:
        return (
            f"Parcel(weight_kg={self.weight_kg!r}, length_cm={self.length_cm!r}, "
            f"width_cm={self.width_cm!r}, height_cm={self.height_cm!r}, "
            f"destination={self.destination!r}, fragile={self.fragile!r}, tags={self.tags!r})"
        )

    def __eq__(self, other: object) -> bool:
        if other.__class__ is not self.__class__:
            return NotImplemented
        return (
            self.weight_kg,
            self.length_cm,
            self.width_cm,
            self.height_cm,
            self.destination,
            self.fragile,
            self.tags,
        ) == (
            other.weight_kg,
            other.length_cm,
            other.width_cm,
            other.height_cm,
            other.destination,
            other.fragile,
            other.tags,
        )

    __hash__ = None  # mutable, so not hashable

    @property
    def volume_cm3(self) -> int:
        return self.length_cm * self.width_cm * self.height_cm

    def billable_weight(self) -> float:
        """Couriers bill the larger of the real weight and the volumetric weight."""
        return max(self.weight_kg, self.volume_cm3 / 5000)
