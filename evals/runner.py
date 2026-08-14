import os
import time
from langchain_ollama import ChatOllama
from evals.logging import get_logger
from evals.models import EvalCase, EvalResult, EvalRunResults

from evals.scorer import aggregate_scores, score
from squawk.agent import run_agent

logger = get_logger("runner")


DEFAULT_MODEL_NAME = "gemma4:31b"
DEFAULT_CASES_PATH = "evals/fixtures/cases.jsonl"
DEFAULT_OUTPUT_PATH = "evals/results/results.json"

if __name__ == "__main__":
    # Ensure output path exists
    os.makedirs(os.path.dirname(DEFAULT_OUTPUT_PATH), exist_ok=True)

    logger.info(
        "starting evaluation runner",
        model_name=DEFAULT_MODEL_NAME,
        cases_path=DEFAULT_CASES_PATH,
    )

    model = ChatOllama(
        model=DEFAULT_MODEL_NAME,
        temperature=0,
        format="json",
        reasoning=False,
    )

    results: list[EvalResult] = []

    for line in open(DEFAULT_CASES_PATH):
        case = EvalCase.model_validate_json(line)
        logger.debug(
            "evaluating case",
            case_id=case.case_id,
            shipment_id=case.shipment.id,
        )

        start_time = time.perf_counter()
        model_actions = run_agent(case.shipment, case.incoming_event, model=model)
        end_time = time.perf_counter()
        latency_ms = (end_time - start_time) * 1000
        logger.debug(
            "model finished running",
            case_id=case.case_id,
            actions=len(model_actions),
            latency_ms=latency_ms,
        )

        diff = score(case.expectation, model_actions)

        logger.debug(
            "scored case",
            case_id=case.case_id,
            should_act=case.expectation.should_act,
            expected_actions=len(case.expectation.actions),
            model_actions=len(model_actions),
            passed=diff.passed,
            precision=diff.precision,
            recall=diff.recall,
        )

        results.append(
            EvalResult(
                case_id=case.case_id,
                model_name=DEFAULT_MODEL_NAME,
                injector=case.injector,
                tags=case.tags,
                should_act=case.expectation.should_act,
                actions=model_actions,
                diff=diff,
                latency_ms=latency_ms,
                error=None,
            )
        )

    summary = aggregate_scores(results)

    run_results = EvalRunResults(
        model=DEFAULT_MODEL_NAME,
        metadata={"cases_path": DEFAULT_CASES_PATH},
        summary=summary,
        results=results,
    )

    with open(DEFAULT_OUTPUT_PATH, "w") as f:
        f.write(run_results.model_dump_json(indent=2))

    logger.info(
        "finished evaluation runner",
        model_name=DEFAULT_MODEL_NAME,
        cases_path=DEFAULT_CASES_PATH,
        output_path=DEFAULT_OUTPUT_PATH,
        total_cases=len(results),
        precision=summary.overall.precision,
        recall=summary.overall.recall,
    )
