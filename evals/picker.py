import glob
import json
import os

import questionary


def list_results_files(results_dir: str) -> list[str]:
    """ISO-timestamp filenames sort chronologically, so reverse = newest first."""
    return sorted(glob.glob(os.path.join(results_dir, "*.json")), reverse=True)


def label(path: str) -> str:
    try:
        with open(path) as f:
            run = json.load(f)
        overall = run["summary"]["overall"]
        return (
            f"{os.path.basename(path)}  {run['model']}  "
            f"{overall['passed_cases']}/{overall['cases']} passed"
        )
    except (OSError, ValueError, KeyError, TypeError):
        return os.path.basename(path)


def pick_results_files(results_dir: str = "evals/results/", count: int = 1) -> list[str]:
    """Interactively pick `count` results files, newest first. Returns [] if
    there is nothing to pick or the user cancels."""
    choices = [questionary.Choice(label(f), value=f) for f in list_results_files(results_dir)]
    if not choices:
        return []
    if count == 1:
        picked = questionary.select("Pick a results file", choices=choices).ask()
        return [picked] if picked else []
    picked = questionary.checkbox(
        f"Pick {count} results files",
        choices=choices,
        validate=lambda sel: len(sel) == count or f"pick exactly {count}",
    ).ask()
    return picked or []
