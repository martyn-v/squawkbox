import json
import random
from langchain_core.prompts import PromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from evals.logging import get_logger
from evals.scoring.results import EvalRun

logger = get_logger("report")

MAX_SAMPLED_FAILURES = 25

SYSTEM_PROMPT_TEMPLATE = PromptTemplate(
    template="""
    You are an evaluation report generator for Squawk, an agentic application that manages shipment exceptions.
    Squawk is given a set of cases: a shipment at a certain state and an incoming event. It must decide which actions, if any, to take in response. 
    You are given a JSON file containing the results of an evaluation run, which includes the model's performance on various test cases. 
    Your task is to generate a concise and informative report summarizing the evaluation results.

    Rules:
    - The report should be structured with clear headings and subheadings.
    - Include a summary of the overall performance metrics, such as precision, recall, and any other relevant statistics.
    - Highlight any notable successes or failures of the model, providing specific examples from the evaluation cases.
    - Offer insights or recommendations for improving the model's performance based on the evaluation results.
    - The report should be written in a professional and objective tone, suitable for stakeholders and team members who are interested in the model's performance.
    - The report must be in Markdown format, with appropriate use of headings, bullet points, and code blocks where necessary.
    - Do not include any personal opinions or subjective statements; focus solely on the data and results
    - The "failure_sample" field is a stratified sample of failing cases, not the full set; all metrics must come from the "summary" field, never be computed from the sample.
""",
    input_variables=[],
)

USER_PROMPT_TEMPLATE = PromptTemplate(
    template="""Eval results: <results>{eval_results}</results>
""",
    input_variables=["eval_results"],
)


def build_report_payload(run: EvalRun) -> dict:
    """Run metadata + summary + a stratified sample of failures, sized to fit a local model's context."""
    rng = random.Random(run.run_at)
    failures = [
        e
        for e in run.results
        if e.error is not None or (e.diff is not None and e.diff.passed is False)
    ]

    buckets: dict[str, list] = {}
    for e in failures:
        buckets.setdefault(e.injector or "clean", []).append(e)

    per_bucket = max(1, MAX_SAMPLED_FAILURES // len(buckets)) if buckets else 0
    results_sample = [
        e
        for bucket in buckets.values()
        for e in rng.sample(bucket, min(per_bucket, len(bucket)))
    ]

    payload = run.model_dump(exclude={"results"})
    payload["failure_sample"] = [e.model_dump() for e in results_sample]
    return payload


def summarize_run_results(model_name: str, model_temperature: float, evals_file: str):
    logger.info(
        "summarizing evaluation results",
        model_name=model_name,
        model_temperature=model_temperature,
        evals_file=evals_file,
    )

    with open(evals_file, "r") as f:
        eval_results = EvalRun.model_validate_json(f.read())

    payload = build_report_payload(eval_results)

    messages = [
        SystemMessage(content=SYSTEM_PROMPT_TEMPLATE.format()),
        HumanMessage(
            content=USER_PROMPT_TEMPLATE.format(eval_results=json.dumps(payload))
        ),
    ]

    model = ChatOllama(
        model=model_name,
        temperature=model_temperature,
    )

    response = model.invoke(messages)
    output_file = evals_file.replace(".json", ".md")

    with open(output_file, "w") as f:
        f.write(
            response.content
            if isinstance(response.content, str)
            else str(response.content)
        )

    logger.info(
        "summarized evaluation results",
        output_file=output_file,
    )
