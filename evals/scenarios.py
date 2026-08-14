from abc import ABC, abstractmethod
from datetime import timedelta
from random import Random


from evals.models import (
    Expectation,
    InjectionResult,
)
from squawk.models import (
    Action,
    ArrivalDelayEvent,
    DepartureDelayEvent,
    EscalateAction,
    Shipment,
    UpdatePropertyAction,
    NotifyAction,
)


class ScenarioInjector(ABC):
    @abstractmethod
    def is_applicable(self, shipment: Shipment) -> bool:
        """Return true if the scenario can be applied to the given shipment, false otherwise."""

    @abstractmethod
    def inject(self, shipment: Shipment, rng: Random) -> InjectionResult:
        """Inject the scenario into the shipment, returning the event and expected outcome."""


class ArrivalDelayInjector(ScenarioInjector):
    """Injects an arrival delay event into a shipment that is currently underway (i.e., has departed but not yet arrived)."""

    def _first_leg_underway(self, shipment: Shipment) -> int | None:
        """Return the index of the first leg that has departed but not yet arrived, or None if no legs match."""
        for i, leg in enumerate(shipment.legs):
            if leg.ata is None and leg.atd is not None:
                return i
        return None

    def is_applicable(self, shipment: Shipment) -> bool:
        # Applicable if the shipment has a leg without an ATA (i.e., not yet arrived)
        return self._first_leg_underway(shipment) is not None

    def inject(self, shipment: Shipment, rng: Random) -> InjectionResult:
        leg_index = self._first_leg_underway(shipment)
        if leg_index is None:
            raise ValueError("ArrivalDelayInjector is not applicable to this shipment.")

        delay_days = rng.randint(1, 5)  # Delay between 1 and 5 days
        is_final_leg = leg_index == len(shipment.legs) - 1

        event = ArrivalDelayEvent(
            leg_index=leg_index,
            delay_days=delay_days,
        )

        actions: list[Action] = [
            UpdatePropertyAction(
                path=f"legs[{leg_index}].eta",
                new_value=shipment.legs[leg_index].eta + timedelta(days=delay_days),
            ),
            NotifyAction(
                recipients=[shipment.contact.email] if shipment.contact.email else [],
            ),
        ]

        if not is_final_leg:
            # If there are subsequent legs, there is a possible rebooking going to happen and so we should escalate.
            actions.append(EscalateAction())

        expectation = Expectation(
            should_act=True,
            actions=actions,
        )

        tags = ["arrival_delay"]
        tags.append("final_leg" if is_final_leg else "connection_risk")

        return InjectionResult(
            event=event,
            expectation=expectation,
            tags=tags,
        )


class DepartureDelayInjector(ScenarioInjector):
    """Injects a departure delay event into a shipment that is currently at the port of loading (i.e., has not yet departed)."""

    def _first_leg_at_port(self, shipment: Shipment) -> int | None:
        """Return the index of the first leg that has not yet departed, or None if no legs match."""
        for i, leg in enumerate(shipment.legs):
            if leg.atd is None:
                return i
        return None

    def is_applicable(self, shipment: Shipment) -> bool:
        # Applicable if the shipment has a leg without an ATD (i.e., not yet departed)
        return self._first_leg_at_port(shipment) is not None

    def inject(self, shipment: Shipment, rng: Random) -> InjectionResult:
        leg_index = self._first_leg_at_port(shipment)
        if leg_index is None:
            raise ValueError(
                "DepartureDelayInjector is not applicable to this shipment."
            )

        delay_days = rng.randint(1, 5)  # Delay between 1 and 5 days
        is_final_leg = leg_index == len(shipment.legs) - 1

        event = DepartureDelayEvent(
            leg_index=leg_index,
            delay_days=delay_days,
        )

        actions: list[Action] = [
            UpdatePropertyAction(
                path=f"legs[{leg_index}].etd",
                new_value=shipment.legs[leg_index].etd + timedelta(days=delay_days),
            ),
            UpdatePropertyAction(
                path=f"legs[{leg_index}].eta",
                new_value=shipment.legs[leg_index].eta + timedelta(days=delay_days),
            ),
            NotifyAction(
                recipients=[shipment.contact.email] if shipment.contact.email else [],
            ),
        ]

        if not is_final_leg:
            # If there are subsequent legs, there is a possible rebooking going to happen and so we should escalate.
            actions.append(EscalateAction())

        expectation = Expectation(
            should_act=True,
            actions=actions,
        )

        tags = ["departure_delay"]
        tags.append("final_leg" if is_final_leg else "connection_risk")

        return InjectionResult(
            event=event,
            expectation=expectation,
            tags=tags,
        )
