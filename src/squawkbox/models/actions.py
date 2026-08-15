from typing import Annotated, Any
from typing_extensions import Literal
from pydantic import BaseModel, Field

from squawkbox.models.shipment import Contact


class UpdatePropertyAction(BaseModel):
    """Action that updates a property on the shipment, such as correcting an ETA or port. The path is a JSON pointer to the property, and new_value is the corrected value."""

    type: Literal["update_property"] = "update_property"
    path: str
    new_value: Any


class NotifyAction(BaseModel):
    """Action that notifies a human operator about something. The message is judge material only, never diffed."""

    type: Literal["notify"] = "notify"
    recipients: Annotated[list[Contact], "List of people to notify"]
    message: str | None = None  # judge material only, never diffed


class EscalateAction(BaseModel):
    """Action that escalates the shipment to a human operator, such as when downstream intervention is required. The reason is judge material only, never diffed."""

    type: Literal["escalate"] = "escalate"
    reason: str | None = None  # judge material only, never diffed


Action = Annotated[
    UpdatePropertyAction | NotifyAction | EscalateAction,
    Field(discriminator="type"),
]


class AgentReply(BaseModel):
    actions: list[Action]
