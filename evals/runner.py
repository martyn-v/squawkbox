from langchain_ollama import ChatOllama
from evals.models import EvalCase, EvalResult

from evals.scorer import aggregate_scores, score
from squawk.agent import run_agent


if __name__ == "__main__":
    model_name = "gemma4:31b"
    model = ChatOllama(
        model=model_name,
        temperature=0,
        format="json",
        reasoning=False,
    )

    results: list[EvalResult] = []

    for line in open("evals/cases.jsonl"):
        case = EvalCase.model_validate_json(line)
        model_actions = run_agent(case.shipment, case.incoming_event, model=model)

        diff = score(case.expectation, model_actions)
        print(diff.model_dump_json(indent=2))
        print("--------------------------------")
        results.append(
            EvalResult(
                case_id=case.case_id,
                model_name=model_name,
                actions=model_actions,
                diff=diff,
                error=None,
            )
        )

    summary = aggregate_scores([r.diff for r in results if r.diff])
    print(summary.model_dump_json(indent=2))
