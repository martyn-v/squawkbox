import inspect
from typing import Annotated, Any, get_args
from typing_extensions import Literal
from pydantic import BaseModel, Field

from squawkbox.models.shipment import Contact


class UpdatePropertyAction(BaseModel):
    """Action that updates a property on the shipment, such as correcting an ETA or port."""

    type: Literal["update_property"] = "update_property"
    path: Annotated[
        str,
        Field(description='Addresses the field to correct, e.g. "legs[0].eta".'),
    ]
    new_value: Annotated[
        Any,
        Field(description="The corrected value. Dates use ISO format (YYYY-MM-DD)."),
    ]


class NotifyAction(BaseModel):
    """Action that notifies a human about an event."""

    type: Literal["notify"] = "notify"
    recipients: Annotated[
        list[Contact], Field(description="Array of contacts to notify about the event.")
    ]
    reason: Annotated[
        str | None,
        Field(description="Briefly explains why the recipients are being notified."),
    ] = None  # judge material only, never diffed


class EscalateAction(BaseModel):
    """Action that escalates the shipment to a human operator, such as when downstream intervention is required."""

    type: Literal["escalate"] = "escalate"
    reason: Annotated[
        str | None,
        Field(description="Briefly explains why the shipment is being escalated."),
    ] = None  # judge material only, never diffed


Action = Annotated[
    UpdatePropertyAction | NotifyAction | EscalateAction,
    Field(discriminator="type"),
]


def actions_to_prompt_text() -> str:
    union, _field_info = get_args(Action)
    members = get_args(union)
    output = []
    for cls in members:
        tag = cls.model_fields["type"].default
        output.append(f'- {tag} (type: "{tag}"): {inspect.cleandoc(cls.__doc__)}')
        output.append("  Fields:")
        for name, data in cls.model_fields.items():
            if name == "type" or data is None:
                continue

            line = f"  - {name} {'(required)' if data.is_required() else '(optional)'}"
            if data.description:
                line += f": {data.description}"
            output.append(line)

    return "\n".join(output)


class AgentReply(BaseModel):
    actions: list[Action]
