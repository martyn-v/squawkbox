import datetime
import os
import time
from langchain_core.runnables import RunnableConfig
from langchain_ollama import ChatOllama
from langfuse import Langfuse
from evals.casefile import load_cases
from evals.langfuse import get_dataset_name, get_run_mirror
from evals.logging import get_logger
from evals.models import CaseFileMeta, EvalCase
from evals.scoring import aggregate_scores, score
from evals.scoring.results import EvalResult, EvalRun
from evals.utils import git_sha
from squawkbox.agent import run_agent, SYSTEM_PROMPT_TEMPLATE
import hashlib

logger = get_logger("runner")


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


def _eval_case(
    case: EvalCase,
    model: ChatOllama,
    config: RunnableConfig | None = None,
) -> EvalResult:
    logger.debug(
        "evaluating case",
        case_id=case.case_id,
        shipment_id=case.shipment.id,
        incoming_event_type=case.incoming_event.type,
    )

    start_time = time.perf_counter()
    try:
        model_actions = run_agent(
            case.shipment, case.incoming_event, model=model, config=config
        )
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


def _run_cases_mirrored(
    cases: list[EvalCase],
    model: ChatOllama,
    langfuse: Langfuse,
    dataset_name: str,
    run_name: str,
    run_metadata: dict[str, str],
    results: list[EvalResult],
) -> None:
    """Evaluate all cases through langfuse.run_experiment so the run shows up
    as an experiment on the dataset (the v4 server has no other supported way
    to attach traces to dataset items).

    The experiment machinery is only the transport: the task delegates to
    _eval_case and appends to `results` as it goes (so the caller's partial
    report on interrupt keeps working), and the evaluator just replays the
    already-computed deterministic diff, looked up via the case_id each
    dataset item carries in its metadata. Errored cases re-raise so the
    trace is marked ERROR and left unscored, matching diff=None locally."""
    from langfuse import Evaluation
    from langfuse.langchain import CallbackHandler

    # Nests a generation observation (rendered prompt, raw reply, model params)
    # under each case's experiment trace.
    agent_config: RunnableConfig = {"callbacks": [CallbackHandler()]}

    dataset = langfuse.get_dataset(dataset_name)
    items_by_case_id = {
        (item.metadata or {}).get("case_id"): item for item in dataset.items
    }
    if any(case.case_id not in items_by_case_id for case in cases):
        logger.warning(
            "langfuse dataset items don't match local cases, run will not "
            "be mirrored; re-push with `uv run -m evals push`",
            dataset_name=dataset_name,
        )
        for case in cases:
            results.append(_eval_case(case, model))
        return

    cases_by_id = {case.case_id: case for case in cases}
    results_by_id: dict[str, EvalResult] = {}

    def task(*, item, **kwargs):
        case_id = (item.metadata or {}).get("case_id")
        result = _eval_case(cases_by_id[case_id], model, config=agent_config)
        results.append(result)
        results_by_id[case_id] = result
        if result.error is not None:
            raise RuntimeError(result.error)
        return [action.model_dump(mode="json") for action in result.actions]

    def squawk_scores(*, metadata, **kwargs):
        case_id = (metadata or {}).get("case_id")
        result = results_by_id.get(case_id) if isinstance(case_id, str) else None
        if result is None or result.diff is None:
            return []
        evaluations = [Evaluation(name="passed", value=float(result.diff.passed))]
        if result.diff.precision is not None:
            evaluations.append(Evaluation(name="precision", value=result.diff.precision))
        if result.diff.recall is not None:
            evaluations.append(Evaluation(name="recall", value=result.diff.recall))
        return evaluations

    langfuse.run_experiment(
        name=run_name,
        run_name=run_name,
        data=[items_by_case_id[case.case_id] for case in cases],
        task=task,
        evaluators=[squawk_scores],
        max_concurrency=1,
        metadata=run_metadata,
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
    langfuse_enabled: bool = True,
) -> str:
    model, output_file, run_at = _setup(
        model_name, model_temperature, cases_path, output_path
    )

    results: list[EvalResult] = []
    complete = False
    cases_meta: CaseFileMeta | None = None
    cases_hash: str | None = None
    langfuse: Langfuse | None = None
    try:
        cases_meta, cases, cases_hash = load_cases(cases_path)
        if cases_meta:
            logger.debug(
                "read casefile metadata",
                generator_version=cases_meta.generator_version,
                seed=cases_meta.seed,
                generated_at=cases_meta.generated_at,
                git_sha=cases_meta.git_sha,
                case_count=cases_meta.case_count,
            )

        langfuse = (
            get_run_mirror(cases_meta, cases_hash) if langfuse_enabled else None
        )
        if langfuse is not None:
            _run_cases_mirrored(
                cases,
                model,
                langfuse,
                get_dataset_name(cases_meta),
                run_name=f"{label} {run_at}" if label else run_at,
                run_metadata={
                    "model": model_name,
                    "model_temperature": str(model_temperature),
                    "git_sha": git_sha() or "unknown",
                    "label": label or "",
                },
                results=results,
            )
        else:
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
        if langfuse is not None:
            langfuse.flush()
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
