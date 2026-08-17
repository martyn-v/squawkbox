from langfuse import get_client
from pydantic import TypeAdapter, ValidationError
from evals.logging import get_logger
from evals.models import CaseFileMeta, CaseFileRow, EvalCase


logger = get_logger("langfuse")

CASE_FILE_ROW_ADAPTER = TypeAdapter(CaseFileRow)


def _load_cases(
    cases_path: str,
) -> tuple[CaseFileMeta, list[EvalCase]]:
    """Parse the whole case file before evaluating anything: a corrupt or
    truncated file is a dataset bug, so fail before spending model calls."""
    meta: CaseFileMeta | None = None
    cases: list[EvalCase] = []

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

    if meta is None:
        raise ValueError(f"missing meta in case file {cases_path}")

    return meta, cases


def push_cases(cases_path: str):
    """Push cases to Langfuse."""
    meta, cases = _load_cases(cases_path)
    langfuse = get_client()

    dataset_name = f"cases-seed{meta.seed}-n{meta.case_count}"

    langfuse.create_dataset(
        name=dataset_name,
        # optional description
        description="My first dataset",
        # optional metadata
        metadata=meta,
    )

    for case in cases:
        langfuse.create_dataset_item(
            id=case.case_id,
            dataset_name=dataset_name,
            # any python object or value, optional
            input={
                "shipment": case.shipment,
                "incoming_event": case.incoming_event,
            },
            # any python object or value, optional
            expected_output=case.expectation,
            # metadata, optional
            metadata={},
        )
