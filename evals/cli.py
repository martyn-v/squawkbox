import click
from dotenv import load_dotenv


DEFAULT_SUMMARIZE_MODEL = "gemma4:31b"
DEFAULT_SUMMARIZE_TEMPERATURE = 0.2

load_dotenv()


@click.group()
def cli():
    """Evaluate the squawkbox agent.

    Typical workflow: generate → run → summarize.
    """
    pass


@cli.command()
@click.option(
    "--seed", default=42, help="Random seed for reproducibility.", show_default=True
)
@click.option(
    "--count", "-n", default=30, help="Number of cases to generate.", show_default=True
)
@click.option(
    "--data",
    type=click.Path(exists=True, dir_okay=False),
    default="evals/data/data.yaml",
    help="Source data file for the generator.",
    show_default=True,
)
@click.option(
    "--output",
    "-o",
    type=click.Path(dir_okay=False, writable=True),
    default="evals/cases/cases.jsonl",
    help="Where to write the generated cases (JSONL).",
    show_default=True,
)
def generate(seed: int, count: int, data: str, output: str):
    """Generate synthetic evaluation cases."""
    from evals.generation import generate

    generate(seed, count, data, output)


@cli.command()
@click.option(
    "--model",
    "-m",
    default="gemma4:31b",
    help="Model to evaluate.",
    show_default=True,
)
@click.option(
    "--temperature",
    "-t",
    default=0.5,
    help="Sampling temperature for the evaluated model.",
    show_default=True,
)
@click.option(
    "--cases",
    type=click.Path(exists=True, dir_okay=False),
    default="evals/cases/cases.jsonl",
    help="Cases file to evaluate against.",
    show_default=True,
)
@click.option(
    "--output",
    "-o",
    type=click.Path(file_okay=False),
    default="evals/results/",
    help="Directory for the results file.",
    show_default=True,
)
@click.option(
    "--label",
    "-l",
    default=None,
    help='What this run is testing, e.g. "tighter escalation rules". '
    "Stored in the results file and shown in the picker.",
)
@click.option(
    "--summarize",
    is_flag=True,
    default=False,
    help="Also write a markdown summary of the results.",
)
@click.option(
    "--langfuse/--no-langfuse",
    default=True,
    help="Mirror the run to Langfuse as an experiment.",
    show_default=True,
)
def run(
    model: str,
    temperature: float,
    cases: str,
    output: str,
    label: str | None,
    summarize: bool,
    langfuse: bool,
):
    """Run the agent against a cases file.

    Writes a timestamped results JSON into the output directory.
    """
    from evals.runner import run

    file = run(model, temperature, cases, output, label=label, langfuse_enabled=langfuse)
    if summarize:
        from evals.report import summarize_run_results

        summarize_run_results(
            DEFAULT_SUMMARIZE_MODEL, DEFAULT_SUMMARIZE_TEMPERATURE, file
        )


@cli.command()
@click.option(
    "--model",
    "-m",
    default=DEFAULT_SUMMARIZE_MODEL,
    help="Model that writes the summary.",
    show_default=True,
)
@click.option(
    "--temperature",
    "-t",
    default=DEFAULT_SUMMARIZE_TEMPERATURE,
    help="Sampling temperature for the summary model.",
    show_default=True,
)
@click.option(
    "--results-file",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Results file to summarize; omit to pick interactively.",
)
def summarize(model: str, temperature: float, results_file: str | None):
    """Summarize a results file to markdown, saved alongside it."""
    from evals.report import summarize_run_results

    if results_file is None:
        from evals.picker import pick_results_files

        picked = pick_results_files()
        if not picked:
            raise click.UsageError("no results file selected")
        results_file = picked[0]

    summarize_run_results(model, temperature, results_file)


@cli.command()
@click.option(
    "--cases",
    type=click.Path(exists=True, dir_okay=False),
    default="evals/cases/cases.jsonl",
    help="Cases file to upload to Langfuse.",
    show_default=True,
)
def push(cases: str):
    """Push cases to a Langfuse dataset."""
    from evals.langfuse import push_cases

    push_cases(cases)


if __name__ == "__main__":
    cli()
