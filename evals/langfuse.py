from langfuse import Langfuse, get_client
from evals.casefile import load_cases
from evals.logging import get_logger
from evals.models import CaseFileMeta


logger = get_logger("langfuse")


def get_dataset_name(cases_meta: CaseFileMeta) -> str:
    return f"cases-seed{cases_meta.seed}-n{cases_meta.case_count}"


def get_run_mirror(cases_meta: CaseFileMeta, cases_hash: str) -> Langfuse | None:
    """Return a client for mirroring an eval run to Langfuse, or None if the
    run can't be attributed to a pushed dataset (server down, no credentials,
    dataset never pushed, or pushed from a different case file). A None means
    the run proceeds locally as before; mirroring is best-effort."""
    dataset_name = get_dataset_name(cases_meta)
    try:
        client = get_client()
        dataset = client.api.datasets.get(dataset_name)
    except Exception as e:
        logger.warning(
            "langfuse unavailable or dataset missing, run will not be mirrored; "
            "push with `uv run -m evals push`",
            dataset_name=dataset_name,
            error=str(e),
        )
        return None

    pushed_hash = (dataset.metadata or {}).get("cases_hash")
    if pushed_hash != cases_hash:
        logger.warning(
            "langfuse dataset was pushed from a different case file, run will "
            "not be mirrored; re-push with `uv run -m evals push`",
            dataset_name=dataset_name,
            pushed_hash=pushed_hash,
            local_hash=cases_hash,
        )
        return None

    return client


def push_cases(cases_path: str):
    """Push cases to Langfuse."""

    meta, cases, hash = load_cases(cases_path)
    langfuse = get_client()

    dataset_name = get_dataset_name(meta)
    logger.info(
        "pushing cases",
        dataset_name=dataset_name,
        cases_path=cases_path,
        case_count=meta.case_count,
    )

    langfuse.create_dataset(
        name=dataset_name,
        metadata={
            "generator_version": meta.generator_version,
            "seed": meta.seed,
            "generated_at": meta.generated_at,
            "git_sha": meta.git_sha,
            "case_count": meta.case_count,
            "cases_hash": hash,
        },
    )

    logger.debug("dataset created", dataset_name=dataset_name)

    for case in cases:
        langfuse.create_dataset_item(
            # item ids are unique per project across datasets, so namespace
            # them ("." not "/": the UI puts the id in a URL path segment);
            # the runner maps items back to cases via metadata.case_id
            id=f"{dataset_name}.{case.case_id}",
            dataset_name=dataset_name,
            input={
                "shipment": case.shipment,
                "incoming_event": case.incoming_event,
            },
            expected_output=case.expectation,
            # case_id lets the runner map experiment items back to local
            # results; injector/tags enable slicing scores in the Langfuse UI
            metadata={
                "case_id": case.case_id,
                "injector": case.injector,
                "tags": case.tags,
            },
        )
        logger.debug("dataset item created", case_id=case.case_id)

    logger.info("finished pushing cases")
