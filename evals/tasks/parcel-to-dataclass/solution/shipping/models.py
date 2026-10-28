"""The two records everything else in shipping passes around."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Address:
    """Where a parcel goes. Immutable, so it can be used as a dict key."""

    street: str
    city: str
    postcode: str
    country: str = "NL"

    @property
    def domestic(self) -> bool:
        return self.country == "NL"


@dataclass
class Parcel:
    """A box with its size in centimetres and weight in kilograms."""

    weight_kg: float
    length_cm: int
    width_cm: int
    height_cm: int
    destination: Address
    fragile: bool = False
    tags: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.weight_kg <= 0:
            raise ValueError("weight must be positive")
        if min(self.length_cm, self.width_cm, self.height_cm) <= 0:
            raise ValueError("every side must be positive")

    @property
    def volume_cm3(self) -> int:
        return self.length_cm * self.width_cm * self.height_cm

    def billable_weight(self) -> float:
        """Couriers bill the larger of the real weight and the volumetric weight."""
        return max(self.weight_kg, self.volume_cm3 / 5000)
