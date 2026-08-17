import json
from langchain_core.prompts import PromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig

from squawkbox.llm import create_model
from squawkbox.models import AgentReply, Shipment, IncomingEvent, Action
from squawkbox.models.actions import (
    NotifyAction,
    UpdatePropertyAction,
    actions_to_prompt_text,
)
from squawkbox.models.shipment import Contact

SYSTEM_PROMPT_TEMPLATE = PromptTemplate(
    template="""You are a shipment exception agent. You are given the current state of a shipment and one incoming event. Decide which actions, if any, to take in response.

Available actions:
<actions>
{actions}
</actions>

Your reply must be a single JSON object with one key, "actions", holding an array of action objects. It must validate against this JSON Schema:

<schema>
{schema}
</schema>

The schema describes the shape of your reply. Never output the schema itself.

Rules:
- Reply with the JSON object only: no prose, no markdown fences.
- If the event warrants no action (e.g. it merely confirms what the shipment state already says), reply with an empty actions array: {{"actions": []}}
- Emit each distinct action at most once. No duplicate or redundant actions.

Example reply:
<example>
{example}
</example>
""",
    input_variables=["schema", "actions", "example"],
)

USER_PROMPT_TEMPLATE = PromptTemplate(
    template="Shipment state: {shipment}\nIncoming event: {incoming_event}\n\nWhat actions should be taken?",
    input_variables=["shipment", "incoming_event"],
)


def run_agent(
    shipment: Shipment,
    incoming_event: IncomingEvent,
    model: BaseChatModel | None = None,
    config: RunnableConfig | None = None,
) -> list[Action]:
    schema = AgentReply.model_json_schema()
    actions = actions_to_prompt_text()
    example = AgentReply(
        actions=[
            UpdatePropertyAction(path="legs[0].eta", new_value="2025-10-22"),
            NotifyAction(
                recipients=[Contact(name="John Doe", email="johndoe@example.org")],
                reason="Customer should be notified about changes in the ETA",
            ),
        ]
    ).model_dump_json()

    messages = [
        SystemMessage(
            content=SYSTEM_PROMPT_TEMPLATE.format(
                schema=json.dumps(schema), actions=actions, example=example
            )
        ),
        HumanMessage(
            content=USER_PROMPT_TEMPLATE.format(
                shipment=shipment.model_dump_json(),
                incoming_event=incoming_event.model_dump_json(),
            )
        ),
    ]

    model = model or create_model(format="json")

    response = model.invoke(messages, config=config)

    raw = (
        response.content if isinstance(response.content, str) else str(response.content)
    )

    reply = AgentReply.model_validate_json(raw)
    return reply.actions
