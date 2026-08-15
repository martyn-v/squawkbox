import datetime
import os
import time
from langchain_ollama import ChatOllama
from pydantic import ValidationError
from evals.logging import get_logger
from evals.models import EvalCase
from evals.scoring import aggregate_scores, score
from evals.scoring.results import EvalResult, EvalRunResults
from squawk.agent import run_agent, SYSTEM_PROMPT_TEMPLATE
import hashlib

logger = get_logger("runner")


def _setup(
    model_name: str, model_temperature: float, cases_path: str, output_path: str
) -> tuple[ChatOllama, str]:
    # Ensure output path exists
    os.makedirs(output_path, exist_ok=True)

    output_file = os.path.join(
        output_path,
        f"{datetime.datetime.now(datetime.timezone.utc).isoformat()}.json",
    )

    logger.info(
        "starting evaluation runner",
        model_name=model_name,
        model_temperature=model_temperature,
        cases_path=cases_path,
        output_path=output_file,
    )

    model = ChatOllama(
        model=model_name,
        temperature=model_temperature,
        format="json",
        reasoning=False,
        client_kwargs={"timeout": 30},
    )

    return model, output_file


def _eval_case(case: EvalCase, model: ChatOllama) -> EvalResult:
    logger.debug(
        "evaluating case",
        case_id=case.case_id,
        shipment_id=case.shipment.id,
        incoming_event_type=case.incoming_event.type,
    )

    start_time = time.perf_counter()
    try:
        model_actions = run_agent(case.shipment, case.incoming_event, model=model)
    except Exception as e:
        logger.error(
            "model failed to run",
            case_id=case.case_id,
            error=str(e),
        )
        return EvalResult(
            case_id=case.case_id,
            injector=case.injector,
            tags=case.tags,
            should_act=case.expectation.should_act,
            actions=[],
            diff=None,
            latency_ms=None,
            error=str(e),
        )
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

    return EvalResult(
        case_id=case.case_id,
        injector=case.injector,
        tags=case.tags,
        should_act=case.expectation.should_act,
        actions=model_actions,
        diff=diff,
        latency_ms=latency_ms,
        error=None,
    )


def _write_report(
    results: list[EvalResult],
    model_name: str,
    cases_path: str,
    model_temperature: float,
    output_file: str,
    complete: bool = True,
) -> EvalRunResults:
    summary = aggregate_scores(results)

    # Calculate system prompt hash for reproducibility
    system_prompt_hash = hashlib.sha256(
        SYSTEM_PROMPT_TEMPLATE.template.encode()
    ).hexdigest()

    run_results = EvalRunResults(
        model=model_name,
        system_prompt_hash=system_prompt_hash,
        metadata={
            "cases_path": cases_path,
            "model_temperature": model_temperature,
            "complete": complete,
        },
        summary=summary,
        results=results,
    )

    with open(output_file, "w") as f:
        f.write(run_results.model_dump_json(indent=2))

    return run_results


def run(
    model_name: str, model_temperature: float, cases_path: str, output_path: str
) -> str:
    model, output_file = _setup(model_name, model_temperature, cases_path, output_path)

    results: list[EvalResult] = []
    complete = False
    try:
        with open(cases_path, "r") as f:
            for lineno, line in enumerate(f, 1):
                # A corrupt case file is a dataset bug, not an agent failure:
                # stop the run rather than silently scoring a smaller dataset.
                try:
                    case = EvalCase.model_validate_json(line)
                except ValidationError as e:
                    raise ValueError(f"corrupt case file {cases_path}:{lineno}") from e
                results.append(_eval_case(case, model))
        complete = True

    except Exception as e:
        logger.error(
            "evaluation runner failed",
            error=str(e),
            model_name=model_name,
            cases_path=cases_path,
            output_path=output_file,
        )
        raise
    finally:
        if results:
            run_results = _write_report(
                results,
                model_name,
                cases_path,
                model_temperature,
                output_file,
                complete=complete,
            )

            logger.info(
                "finished evaluation runner",
                model_name=model_name,
                cases_path=cases_path,
                output_path=output_file,
                total_cases=len(run_results.results),
                precision=run_results.summary.overall.precision,
                recall=run_results.summary.overall.recall,
            )

    return output_file
