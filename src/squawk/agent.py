import json
from langchain_core.prompts import PromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.language_models import BaseChatModel

from squawk.llm import default_model
from squawk.models import AgentReply, Shipment, IncomingEvent, Action

SYSTEM_PROMPT_TEMPLATE = PromptTemplate(
    template="""You are a shipment exception agent. You are given the current state of a shipment and one incoming event. Decide which actions, if any, to take in response.

Available actions:
- update_property: correct a field on the shipment. "path" addresses the field (e.g. "legs[0].eta"), "new_value" is the corrected value. Dates use ISO format (YYYY-MM-DD).
- notify: inform stakeholders. "recipients" is a list of recipient names; "message" briefly explains why.
- escalate: hand the shipment over to a human operator for further intervention, such as rebooking a connected leg. "reason" briefly explains why.

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
{{"actions": [{{"type": "update_property", "path": "legs[1].eta", "new_value": "2026-09-12"}}, {{"type": "notify", "recipients": ["ops"], "message": "ETA pushed 3 days due to port congestion"}}]}}""",
    input_variables=["schema"],
)

USER_PROMPT_TEMPLATE = PromptTemplate(
    template="Shipment state: {shipment}\nIncoming event: {incoming_event}\n\nWhat actions should be taken?",
    input_variables=["shipment", "incoming_event"],
)


def run_agent(
    shipment: Shipment,
    incoming_event: IncomingEvent,
    model: BaseChatModel | None = None,
) -> list[Action]:
    schema = AgentReply.model_json_schema()

    messages = [
        SystemMessage(content=SYSTEM_PROMPT_TEMPLATE.format(schema=json.dumps(schema))),
        HumanMessage(
            content=USER_PROMPT_TEMPLATE.format(
                shipment=shipment.model_dump_json(),
                incoming_event=incoming_event.model_dump_json(),
            )
        ),
    ]

    model = model or default_model()

    response = model.invoke(messages)

    raw = (
        response.content if isinstance(response.content, str) else str(response.content)
    )

    reply = AgentReply.model_validate_json(raw)
    return reply.actions
