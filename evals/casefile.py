import hashlib

from pydantic import TypeAdapter, ValidationError

from evals.models import CaseFileMeta, CaseFileRow, EvalCase

CASE_FILE_ROW_ADAPTER = TypeAdapter(CaseFileRow)


def load_cases(
    cases_path: str,
) -> tuple[CaseFileMeta, list[EvalCase], str]:
    """Parse the whole case file before evaluating anything: a corrupt or
    truncated file is a dataset bug, so fail before spending model calls.

    Returns:
        A (meta, cases, cases_hash) tuple:
        - meta: the file's CaseFileMeta provenance header (never None; missing
          meta raises ValueError)
        - cases: the EvalCases in file order
        - cases_hash: dataset identity as "sha256:<hexdigest>", hashed over
          each case's canonical JSON rather than raw lines
    """
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

    if meta is None:
        raise ValueError("casefile has no metadata")

    if meta and meta.case_count != len(cases):
        raise ValueError(
            f"case file {cases_path} declares {meta.case_count} cases "
            f"but contains {len(cases)}"
        )

    return meta, cases, f"sha256:{digest.hexdigest()}"
