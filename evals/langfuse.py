from langfuse import get_client
from evals.casefile import load_cases
from evals.logging import get_logger
from evals.models import CaseFileMeta


logger = get_logger("langfuse")


def get_dataset_name(cases_meta: CaseFileMeta) -> str:
    return f"cases-seed{cases_meta.seed}-n{cases_meta.case_count}"


def push_cases(cases_path: str):
    """Push cases to Langfuse."""
    meta, cases, hash = load_cases(cases_path)
    langfuse = get_client()

    dataset_name = get_dataset_name(meta)

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

    for case in cases:
        langfuse.create_dataset_item(
            id=case.case_id,
            dataset_name=dataset_name,
            input={
                "shipment": case.shipment,
                "incoming_event": case.incoming_event,
            },
            expected_output=case.expectation,
            metadata={},
        )
