from random import Random

from faker import Faker
from faker.providers import BaseProvider


class LogisticsProvider(BaseProvider):
    vessel_prefixes = ("MSC", "MV", "CMA CGM", "Ever", "Maersk", "OOCL", "HMM")
    vessel_names = (
        "Aurora",
        "Meridian",
        "Pacific Dawn",
        "Northern Star",
        "Endeavour",
        "Fortune",
        "Harmony",
        "Triton",
        "Valiant",
    )
    airline_codes = ("EK", "LH", "SQ", "CX", "QR", "KL", "BA", "AF")

    def vessel_name(self) -> str:
        return f"{self.random_element(self.vessel_prefixes)} {self.random_element(self.vessel_names)}"

    def voyage_number(self) -> str:
        return f"{self.random_int(100, 999)}{self.random_element(['N', 'E', 'S', 'W'])}"

    def vessel_voyage(self) -> str:
        return f"{self.vessel_name()} - {self.voyage_number()}"

    def flight_number(self) -> str:
        # Cargo flight numbers are typically 3-4 digits
        return f"{self.random_element(self.airline_codes)}{self.random_int(100, 9999)}"


def make_faker(rng: Random) -> Faker:
    """Create a Faker with the LogisticsProvider registered, seeded deterministically from the given rng."""
    fake = Faker()
    fake.add_provider(LogisticsProvider)
    fake.seed_instance(rng.randint(0, 2**32))
    return fake
