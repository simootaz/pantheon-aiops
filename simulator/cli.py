"""Command line entrypoint for the simulator.

    pantheon-sim list
    pantheon-sim run bad_deploy_5xx --speed 4320
    pantheon-sim run memory_leak --speed 1        # real time
    pantheon-sim baseline --minutes 2

`--speed` is the compression factor and defaults to fast, because that is what
makes a scenario finish inside a test. Real time is always available, and the
banner prints what the chosen speed means in wall clock terms so nobody has to
work it out from a number.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import sys

import typer

from simulator import clock as simclock
from simulator.runner import ScenarioRunner
from simulator.scenario import load, load_all

app = typer.Typer(
    name="pantheon-sim",
    help="Synthetic signals for Pantheon: metrics, logs and pipeline events.",
    no_args_is_help=True,
    add_completion=False,
)


def _echo(message: str) -> None:
    typer.echo(f"  {message}")


@app.command("list")
def list_scenarios() -> None:
    """List the available scenarios and the answer each one expects."""
    scenarios = load_all()
    typer.echo(f"{len(scenarios)} scenarios\n")
    for scenario in scenarios:
        typer.echo(typer.style(scenario.name, bold=True))
        typer.echo(f"  {scenario.title}")
        typer.echo(
            f"  expects  {scenario.expected_root_cause.category.value}"
            f" on {scenario.expected_root_cause.subject}"
        )
        typer.echo(
            f"  phases   {len(scenario.phases)}  ({scenario.total_seconds / 3600:.0f}h simulated)"
        )
        typer.echo("")


@app.command()
def run(
    scenario_name: str = typer.Argument(..., metavar="SCENARIO"),
    speed: float = typer.Option(
        simclock.FAST, "--speed", "-s", help="Compression factor. 1 is real time."
    ),
    pushgateway: str = typer.Option("localhost:9091", help="Prometheus pushgateway host:port."),
    loki_url: str = typer.Option("http://localhost:3100", help="Loki base URL."),
    webhook_url: str = typer.Option(
        "http://localhost:8000/webhooks/gitlab", help="Pantheon webhook endpoint."
    ),
    tick_seconds: float = typer.Option(60.0, help="Simulated seconds per push."),
    no_pipelines: bool = typer.Option(False, help="Skip GitLab webhooks."),
) -> None:
    """Run one scenario end to end against a live stack."""
    try:
        scenario = load(scenario_name)
    except FileNotFoundError as error:
        typer.secho(str(error), fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from error

    expected_wall = scenario.total_seconds / speed
    typer.echo(typer.style(f"\n{scenario.title}", bold=True))
    typer.echo(f"  {scenario.description}")
    typer.echo(f"  speed      {simclock.describe(speed)}")
    typer.echo(
        f"  simulated  {scenario.total_seconds / 3600:.1f}h"
        f"  ->  about {expected_wall:.0f}s of wall clock"
    )
    typer.echo(
        f"  expects    {scenario.expected_root_cause.category.value}"
        f" on {scenario.expected_root_cause.subject}\n"
    )

    runner = ScenarioRunner(
        pushgateway=pushgateway,
        loki_url=loki_url,
        webhook_url=webhook_url,
        tick_seconds=tick_seconds,
        on_event=_echo,
    )

    try:
        report = runner.run(scenario, speed=speed, send_pipelines=not no_pipelines)
    except KeyboardInterrupt:
        typer.secho("\ninterrupted", fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(code=130) from None
    except Exception as error:
        typer.secho(f"\nrun failed: {error}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from error

    typer.echo("")
    typer.echo(typer.style("done", bold=True))
    typer.echo(f"  ticks      {report.ticks}")
    typer.echo(f"  metrics    {report.metrics_pushes} pushes")
    typer.echo(f"  logs       {report.log_lines} lines")
    typer.echo(f"  pipelines  {report.pipelines_sent} events")
    typer.echo(f"  wall       {report.wall_seconds:.1f}s")
    typer.echo(f"  phases     {', '.join(report.phases_entered) or 'none'}")


@app.command()
def baseline(
    minutes: float = typer.Option(2.0, help="Wall minutes to run for."),
    speed: float = typer.Option(simclock.FAST, "--speed", "-s", help="Compression factor."),
    pushgateway: str = typer.Option("localhost:9091"),
    loki_url: str = typer.Option("http://localhost:3100"),
    tick_seconds: float = typer.Option(60.0),
) -> None:
    """Emit normal behaviour only, with no fault injected.

    Useful for looking at the seasonality directly, and for giving a detector
    something to learn from before a scenario runs.
    """
    simulated = minutes * 60.0 * speed
    typer.echo(typer.style("\nBaseline", bold=True))
    typer.echo(f"  speed      {simclock.describe(speed)}")
    typer.echo(f"  simulated  {simulated / 3600:.1f}h over {minutes:.1f} wall minutes\n")

    runner = ScenarioRunner(
        pushgateway=pushgateway, loki_url=loki_url, tick_seconds=tick_seconds, on_event=_echo
    )
    try:
        report = runner.baseline(speed=speed, simulated_seconds=simulated)
    except KeyboardInterrupt:
        typer.secho("\ninterrupted", fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(code=130) from None

    typer.echo("")
    typer.echo(f"  {report.metrics_pushes} pushes, {report.log_lines} log lines")


def main() -> None:
    """Console-script entrypoint."""
    app()


if __name__ == "__main__":
    sys.exit(app())
