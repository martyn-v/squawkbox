import click

DEFAULT_SUMMARIZE_MODEL = "gemma4:31b"
DEFAULT_SUMMARIZE_TEMPERATURE = 0.2


@click.group()
def cli():
    """Command line interface for the evals package."""
    pass


@cli.command()
@click.option(
    "--seed", default=42, help="Random seed for reproducibility.", show_default=True
)
@click.option(
    "--cases", default=30, help="Number of cases to generate.", show_default=True
)
@click.option(
    "--data",
    type=click.Path(exists=True, dir_okay=False),
    default="evals/data/data.yaml",
    help="Path to the data file.",
    show_default=True,
)
@click.option(
    "--output",
    type=click.Path(dir_okay=False, writable=True),
    default="evals/cases/cases.jsonl",
    help="Path to the output file.",
    show_default=True,
)
def generate(seed: int, cases: int, data: str, output: str):
    """Generate evaluation cases."""
    from evals.generation import generate

    generate(seed, cases, data, output)


@cli.command()
@click.option(
    "--model",
    default="gemma4:31b",
    help="Name of the model to evaluate.",
    show_default=True,
)
@click.option(
    "--temperature",
    default=0.5,
    help="Temperature of the model to evaluate.",
    show_default=True,
)
@click.option(
    "--cases",
    type=click.Path(exists=True, dir_okay=False),
    default="evals/cases/cases.jsonl",
    help="Path to the evaluation cases file.",
    show_default=True,
)
@click.option(
    "--output",
    type=click.Path(file_okay=False),
    default="evals/results/",
    help="Path to the output directory.",
    show_default=True,
)
@click.option(
    "--summarize",
    is_flag=True,
    help="Summarize the evaluation results to a markdown file.",
    default=False,
    show_default=True,
)
def run(model: str, temperature: float, cases: str, output: str, summarize: bool):
    """Run the evaluation runner."""
    from evals.runner import run

    file = run(model, temperature, cases, output)
    if summarize:
        from evals.report import summarize_run_results

        summarize_run_results(
            DEFAULT_SUMMARIZE_MODEL, DEFAULT_SUMMARIZE_TEMPERATURE, file
        )


@cli.command()
@click.option(
    "--model",
    default=DEFAULT_SUMMARIZE_MODEL,
    help="Name of the model to use for report generation.",
    show_default=True,
)
@click.option(
    "--temperature",
    default=DEFAULT_SUMMARIZE_TEMPERATURE,
    help="Temperature of the model to evaluate.",
    show_default=True,
)
@click.option(
    "--evals_file",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Path to the evaluation results file. Omit to pick interactively.",
    show_default=True,
)
def summarize(model: str, temperature: float, evals_file: str | None):
    """Use LLM to summarize evaluation results to a markdown file."""
    from evals.report import summarize_run_results

    if evals_file is None:
        from evals.picker import pick_results_files

        picked = pick_results_files()
        if not picked:
            raise click.UsageError("no results file selected")
        evals_file = picked[0]

    summarize_run_results(model, temperature, evals_file)


if __name__ == "__main__":
    cli()
