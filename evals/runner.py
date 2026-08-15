import datetime
import os
import time
from langchain_ollama import ChatOllama
from pydantic import TypeAdapter, ValidationError
from evals.logging import get_logger
from evals.models import CaseFileMeta, CaseFileRow, EvalCase
from evals.scoring import aggregate_scores, score
from evals.scoring.results import EvalResult, EvalRun
from evals.utils import git_sha
from squawk.agent import run_agent, SYSTEM_PROMPT_TEMPLATE
import hashlib

logger = get_logger("runner")
CASE_FILE_ROW_ADAPTER = TypeAdapter(CaseFileRow)


def _setup(
    model_name: str, model_temperature: float, cases_path: str, output_path: str
) -> tuple[ChatOllama, str, str]:
    # Ensure output path exists
    os.makedirs(output_path, exist_ok=True)

    run_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    output_file = os.path.join(output_path, f"{run_at}.json")

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

    return model, output_file, run_at


def _load_cases(
    cases_path: str,
) -> tuple[CaseFileMeta | None, list[EvalCase], str]:
    """Parse the whole case file before evaluating anything: a corrupt or
    truncated file is a dataset bug, so fail before spending model calls."""
    meta: CaseFileMeta | None = None
    cases: list[EvalCase] = []
    digest = hashlib.sha256()

    with open(cases_path, "r") as f:
        for lineno, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                row = CASE_FILE_ROW_ADAPTER.validate_json(line)
            except ValidationError as e:
                raise ValueError(f"corrupt case file {cases_path}:{lineno}") from e

            if isinstance(row, CaseFileMeta):
                meta = row
            else:
                cases.append(row)
                # Hash canonical JSON, not raw lines, so reformatting the
                # file doesn't change the dataset's identity.
                digest.update(row.model_dump_json().encode())
                digest.update(b"\n")

    if meta and meta.case_count != len(cases):
        raise ValueError(
            f"case file {cases_path} declares {meta.case_count} cases "
            f"but contains {len(cases)}"
        )

    return meta, cases, f"sha256:{digest.hexdigest()}"


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
    cases_meta: CaseFileMeta | None,
    cases_hash: str | None,
    model_temperature: float,
    output_file: str,
    run_at: str,
    complete: bool = True,
    label: str | None = None,
) -> EvalRun:
    summary = aggregate_scores(results)

    # Calculate system prompt hash for reproducibility
    system_prompt_hash = hashlib.sha256(
        SYSTEM_PROMPT_TEMPLATE.template.encode()
    ).hexdigest()

    run_results = EvalRun(
        model=model_name,
        model_temperature=model_temperature,
        system_prompt_hash=system_prompt_hash,
        git_sha=git_sha() or "unknown",
        cases_path=cases_path,
        cases_meta=cases_meta,
        cases_hash=cases_hash,
        label=label,
        run_at=run_at,
        complete=complete,
        summary=summary,
        results=results,
    )

    with open(output_file, "w") as f:
        # kind is the case-file discriminator; it's noise in a report
        f.write(run_results.model_dump_json(indent=2, exclude={"cases_meta": {"kind"}}))

    return run_results


def run(
    model_name: str,
    model_temperature: float,
    cases_path: str,
    output_path: str,
    label: str | None = None,
) -> str:
    model, output_file, run_at = _setup(
        model_name, model_temperature, cases_path, output_path
    )

    results: list[EvalResult] = []
    complete = False
    cases_meta: CaseFileMeta | None = None
    cases_hash: str | None = None
    try:
        cases_meta, cases, cases_hash = _load_cases(cases_path)
        if cases_meta:
            logger.debug(
                "read casefile metadata",
                generator_version=cases_meta.generator_version,
                seed=cases_meta.seed,
                generated_at=cases_meta.generated_at,
                git_sha=cases_meta.git_sha,
                case_count=cases_meta.case_count,
            )

        for case in cases:
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
                cases_meta,
                cases_hash,
                model_temperature,
                output_file,
                run_at,
                complete=complete,
                label=label,
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
