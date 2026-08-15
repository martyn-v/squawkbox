import click


@click.group()
def cli():
    """Command line interface for the evals package."""
    pass


@cli.command()
@click.option(
    "--seed", default=42, help="Random seed for reproducibility.", show_default=True
)
@click.option(
    "--variants", default=10, help="Number of variants to generate.", show_default=True
)
@click.option(
    "--data",
    type=click.Path(exists=True, dir_okay=False),
    default="evals/artifacts/data.yaml",
    help="Path to the data file.",
    show_default=True,
)
@click.option(
    "--output",
    type=click.Path(dir_okay=False, writable=True),
    default="evals/fixtures/cases.jsonl",
    help="Path to the output file.",
    show_default=True,
)
def generate(seed: int, variants: int, data: str, output: str):
    """Generate evaluation cases."""
    from evals.generator import generate

    generate(seed, variants, data, output)


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
    default="evals/fixtures/cases.jsonl",
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
def run(model: str, temperature: float, cases: str, output: str):
    """Run the evaluation runner."""
    from evals.runner import run

    run(model, temperature, cases, output)


if __name__ == "__main__":
    cli()
