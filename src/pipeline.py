"""
pipeline.py — Orchestrate the full stockpile monitoring pipeline.

Runs: fetch → classify → measure → report
"""

import subprocess
import sys

import click
from rich.console import Console
from rich.panel import Panel

console = Console()

STEPS = [
    ("🛰️  Fetching imagery", "src/fetch_imagery.py"),
    ("🔬 Classifying pixels", "src/classify.py"),
    ("📏 Measuring stockpiles", "src/measure.py"),
    ("📊 Generating report", "src/report.py"),
]


@click.command()
@click.option("--site", required=True, help="Site ID")
@click.option("--months", default=6, help="Months to look back")
@click.option("--max-cloud", default=20, help="Max cloud cover %")
def main(site: str, months: int, max_cloud: int):
    """Run the full stockpile monitoring pipeline."""
    console.print(Panel.fit(
        f"[bold]Sentinel Stockpile Pipeline[/bold]\n"
        f"Site: {site} | Lookback: {months} months | Max cloud: {max_cloud}%",
        border_style="green",
    ))

    for step_name, script in STEPS:
        console.print(f"\n{'='*60}")
        console.print(f"[bold]{step_name}[/bold]")
        console.print(f"{'='*60}")

        cmd = [sys.executable, script, "--site", site]
        if script == "src/fetch_imagery.py":
            cmd += ["--months", str(months), "--max-cloud", str(max_cloud)]

        result = subprocess.run(cmd, cwd=".")
        if result.returncode != 0:
            console.print(f"[red]Step failed: {step_name}[/red]")
            sys.exit(1)

    console.print(Panel.fit(
        f"[bold green]✅ Pipeline complete for {site}[/bold green]\n"
        f"Output: output/{site}/",
        border_style="green",
    ))


if __name__ == "__main__":
    main()
