"""Per-module tests for the simulator, with the network stubbed.

`tests/integration/test_simulator_data.py` proves the *data* is right against a
real Prometheus and a real Loki. It cannot run on every commit, so these cover
the code paths: every template renders, every shape behaves, every CLI command
works, and both push bodies are the shape the servers expect.

The division matters. Coverage from an integration gate that CI runs separately
is coverage `make test` never sees, and a module can rot to zero without anyone
noticing until the ten-minute job goes red.

Phase: 1 - Contracts & First Agent Path
"""

from __future__ import annotations

import json
from itertools import pairwise
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from simulator.cli import app
from simulator.clock import FAST, REALTIME, SECONDS_PER_DAY, SimClock, describe
from simulator.cluster import NODES, NODES_BY_NAME, PODS, PODS_BY_NAME
from simulator.log_generator import TEMPLATES, LogGenerator, LogLine
from simulator.metrics_generator import NOISE as NOISE_TABLE
from simulator.metrics_generator import MetricsGenerator, require_every_metric
from simulator.pipeline_generator import PipelineGenerator
from simulator.runner import ScenarioRunner
from simulator.scenario import (
    Deviation,
    MetricName,
    Phase,
    Shape,
    load,
    load_all,
)

POD = PODS_BY_NAME["checkout-7d4f9b-a1"]
runner_cli = CliRunner()


def _client(handler: Any) -> httpx.Client:
    """An httpx client that never leaves the process."""
    return httpx.Client(transport=httpx.MockTransport(handler))


# --- clock -------------------------------------------------------------------


def test_clock_maps_simulated_time_onto_wall_time() -> None:
    clock = SimClock(speed=100.0)
    assert clock.wall_for(1000.0) == pytest.approx(10.0)
    assert not clock.realtime
    assert SimClock(speed=REALTIME).realtime


def test_clock_rejects_a_speed_that_cannot_advance() -> None:
    """Zero or negative speed would divide by zero or run time backwards."""
    with pytest.raises(ValueError, match="positive"):
        SimClock(speed=0.0)
    with pytest.raises(ValueError, match="positive"):
        SimClock(speed=-1.0)


def test_clock_reports_position_within_the_simulated_day() -> None:
    clock = SimClock(speed=1.0, origin=9 * 3600.0)
    assert clock.time_of_day() == pytest.approx(9 * 3600.0, abs=5.0)
    assert clock.day_fraction() == pytest.approx(0.375, abs=0.01)
    assert clock.now() >= 9 * 3600.0


def test_describe_explains_the_compression_in_words() -> None:
    """The CLI prints this, so nobody has to divide 86400 by a number."""
    assert "real time" in describe(REALTIME)
    assert "20 wall seconds" in describe(FAST)
    assert "wall minutes" in describe(SECONDS_PER_DAY / 600)


# --- metrics -----------------------------------------------------------------


@pytest.mark.parametrize("shape", list(Shape))
def test_every_shape_produces_a_bounded_factor(shape: Shape) -> None:
    """A shape returning more than 1 would scale a deviation past its target."""
    for progress in (0.0, 0.25, 0.5, 0.75, 1.0):
        factor = MetricsGenerator._shape_factor(shape, progress)
        assert 0.0 <= factor <= 1.0, f"{shape} at {progress} gave {factor}"


def test_shapes_are_actually_different_from_one_another() -> None:
    """Four names for one curve would make the scenario vocabulary a lie."""
    midway = {shape: MetricsGenerator._shape_factor(shape, 0.5) for shape in Shape}
    assert midway[Shape.STEP] == 1.0
    assert midway[Shape.RAMP] == pytest.approx(0.5)
    assert midway[Shape.SPIKE] > midway[Shape.RAMP]
    assert len(set(midway.values())) >= 3


def test_shape_progress_is_clamped_outside_the_phase() -> None:
    assert MetricsGenerator._shape_factor(Shape.RAMP, -2.0) == 0.0
    assert MetricsGenerator._shape_factor(Shape.RAMP, 5.0) == 1.0


def test_a_factor_deviation_scales_and_an_offset_adds() -> None:
    generator = MetricsGenerator()
    scaled = generator._apply(10.0, Deviation(metric=MetricName.CPU, factor=3.0), 1.0)
    added = generator._apply(10.0, Deviation(metric=MetricName.RESTARTS, offset=4.0), 1.0)
    assert scaled == pytest.approx(30.0)
    assert added == pytest.approx(14.0)


def test_a_deviation_is_absent_before_its_phase_begins() -> None:
    """At zero progress a deviation must leave the baseline alone."""
    generator = MetricsGenerator()
    assert generator._apply(10.0, Deviation(metric=MetricName.CPU, factor=9.0), 0.0) == 10.0


def test_a_phase_only_touches_the_pods_it_targets() -> None:
    """A fault leaking into every pod would make root-cause attribution untestable."""
    generator = MetricsGenerator()
    phase = Phase(
        name="spike",
        start_seconds=0.0,
        duration_seconds=600.0,
        target="search",
        deviations=[Deviation(metric=MetricName.CPU, factor=5.0, shape=Shape.STEP)],
    )
    search = PODS_BY_NAME["search-2f6b8c-a1"]
    assert generator.sample(search, MetricName.CPU, 300.0, [phase]) > search.base_cpu_cores * 2
    untouched = generator.sample(POD, MetricName.CPU, 300.0, [phase])
    assert untouched < POD.base_cpu_cores * 2


def test_metrics_push_sends_an_exposition_body_the_gateway_accepts() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    generator = MetricsGenerator()
    with _client(handler) as client:
        generator.push(3600.0, [], 60.0, client)

    assert len(seen) == 1
    request = seen[0]
    # PUT replaces the group; POST would merge and a stopped pod would keep
    # reporting its last value forever.
    assert request.method == "PUT"
    assert request.url.path == "/metrics/job/pantheon-sim"

    body = request.content.decode()
    for metric in (
        "pantheon_pod_cpu_cores",
        "pantheon_pod_memory_working_set_bytes",
        "pantheon_http_requests_total",
        "pantheon_node_disk_used_bytes",
    ):
        assert metric in body, f"{metric} missing from the push"
    for pod in PODS:
        assert pod.name in body, f"{pod.name} missing from the push"


def test_counters_only_ever_increase_across_pushes() -> None:
    """A counter that goes down makes Prometheus infer a reset.

    `rate()` then reports a phantom spike over that window, which is
    indistinguishable from the fault the scenario is trying to inject.
    """
    bodies: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(request.content.decode())
        return httpx.Response(200)

    generator = MetricsGenerator()
    with _client(handler) as client:
        for tick in range(6):
            generator.push(tick * 600.0, [], 600.0, client)

    def total(body: str) -> float:
        return sum(
            float(line.rsplit(" ", 1)[1])
            for line in body.splitlines()
            if line.startswith("pantheon_http_requests_total") and 'status="200"' in line
        )

    totals = [total(body) for body in bodies]
    assert all(later >= earlier for earlier, later in pairwise(totals)), (
        f"request counter decreased across pushes: {totals}"
    )
    assert totals[-1] > totals[0], "the counter never advanced at all"


def test_node_disk_is_reported_for_every_node() -> None:
    bodies: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(request.content.decode())
        return httpx.Response(200)

    with _client(handler) as client:
        MetricsGenerator().push(0.0, [], 60.0, client)

    for node in NODES:
        assert f'node="{node.name}"' in bodies[0]


# --- logs --------------------------------------------------------------------


@pytest.mark.parametrize("template", sorted(TEMPLATES))
def test_every_template_renders_to_valid_json(template: str) -> None:
    """A missing placeholder raises mid-run, on whichever tick first uses it.

    Rendering every template here is what turns that into a commit-time failure.
    """
    line = LogGenerator().render(template, POD, 43_200.0)
    parsed = json.loads(line)
    assert parsed["msg"], f"{template} rendered without a message"
    assert parsed["level"] in {"info", "warn", "error"}


def test_rendered_lines_vary_so_they_do_not_collapse_to_one_cluster() -> None:
    """Identical lines make the stream trivially compressible, and useless."""
    generator = LogGenerator()
    rendered = {generator.render("request", POD, 43_200.0) for _ in range(20)}
    assert len(rendered) > 5, f"only {len(rendered)} distinct lines out of 20"


def test_phase_lines_carry_the_level_the_scenario_asked_for() -> None:
    lines = LogGenerator().phase_lines(POD, "pool_exhausted", 60.0, "error", 60.0, 0.0)
    assert lines, "a 60/minute pattern over 60s produced nothing"
    assert {line.level for line in lines} == {"error"}


def test_log_push_groups_by_pod_and_level_with_rising_timestamps() -> None:
    """Loki rejects out-of-order writes within a stream."""
    payloads: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(204)

    generator = LogGenerator()
    lines = [
        LogLine(POD, "info", generator.render("request", POD, 0.0)),
        LogLine(POD, "info", generator.render("request", POD, 1.0)),
        LogLine(POD, "error", generator.render("request_error", POD, 2.0)),
    ]
    with _client(handler) as client:
        assert generator.push(lines, client) == 3

    streams = payloads[0]["streams"]
    assert {stream["stream"]["level"] for stream in streams} == {"info", "error"}
    for stream in streams:
        assert stream["stream"]["pod"] == POD.name
        assert stream["stream"]["job"] == "pantheon-sim"
        stamps = [int(value[0]) for value in stream["values"]]
        assert stamps == sorted(stamps), "timestamps are not monotonic within a stream"


def test_pushing_nothing_makes_no_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("an empty push should not reach Loki")

    with _client(handler) as client:
        assert LogGenerator().push([], client) == 0


def test_sampling_ratio_is_one_when_a_tick_is_short_enough() -> None:
    """Short ticks must not be sampled at all, or real time would lose lines."""
    assert LogGenerator().sampling_ratio(1.0) == 1.0
    assert LogGenerator().sampling_ratio(3600.0) < 0.01


# --- pipelines ---------------------------------------------------------------


def test_pipeline_payload_matches_the_gitlab_hook_shape() -> None:
    payload = PipelineGenerator().pipeline_payload(status="failed", failed_jobs=["integration"])
    assert payload["object_kind"] == "pipeline"
    assert payload["object_attributes"]["status"] == "failed"
    assert payload["project"]["path_with_namespace"]
    failed = [build for build in payload["builds"] if build["status"] == "failed"]
    assert [build["name"] for build in failed] == ["integration"]


def test_pipeline_duration_is_the_sum_of_its_builds() -> None:
    payload = PipelineGenerator().pipeline_payload()
    assert payload["object_attributes"]["duration"] == int(
        sum(build["duration"] for build in payload["builds"])
    )


def test_merge_request_payload_matches_the_gitlab_hook_shape() -> None:
    payload = PipelineGenerator().merge_request_payload(action="merge")
    assert payload["object_kind"] == "merge_request"
    assert payload["object_attributes"]["state"] == "merged"
    assert payload["object_attributes"]["target_branch"] == "main"


def test_pipeline_ids_do_not_repeat() -> None:
    """Two pipelines sharing an id would collapse into one investigation."""
    generator = PipelineGenerator()
    ids = {generator.pipeline_payload()["object_attributes"]["id"] for _ in range(10)}
    assert len(ids) == 10


def test_send_posts_as_gitlab_does_and_reports_the_response() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(202, json={"investigation_id": "inv-1"})

    generator = PipelineGenerator()
    with _client(handler) as client:
        result = generator.send_pipeline(client, status="failed", failed_jobs=["unit"])

    assert seen[0].headers["X-Gitlab-Event"] == "Pipeline Hook"
    assert result.http_status == 202
    assert result.investigation_id == "inv-1"
    assert result.failed_jobs == ["unit"]


def test_send_merge_request_uses_the_merge_request_event_header() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(202, text="accepted")

    with _client(handler) as client:
        result = PipelineGenerator().send_merge_request(client)

    assert seen[0].headers["X-Gitlab-Event"] == "Merge Request Hook"
    # A non-JSON response must not crash the run.
    assert result.investigation_id is None


# --- scenarios ---------------------------------------------------------------


def test_a_deviation_needs_exactly_one_of_factor_or_offset() -> None:
    """Both would be ambiguous; neither would inject nothing and look fine."""
    with pytest.raises(ValueError):
        Deviation(metric=MetricName.CPU)
    with pytest.raises(ValueError):
        Deviation(metric=MetricName.CPU, factor=2.0, offset=1.0)


def test_loading_a_scenario_that_does_not_exist_names_the_alternatives() -> None:
    with pytest.raises(FileNotFoundError) as error:
        load("no_such_scenario")
    assert "bad_deploy_5xx" in str(error.value)


def test_phases_at_is_measured_after_the_baseline() -> None:
    """Phase offsets are relative to the end of the baseline, not to time zero."""
    scenario = load("bad_deploy_5xx")
    assert scenario.phases_at(0.0) == []
    assert scenario.phases_at(scenario.baseline_seconds / 2) == []
    landed = {phase.name for phase in scenario.phases_at(scenario.baseline_seconds + 1.0)}
    assert "deploy_lands" in landed


def test_total_seconds_covers_the_baseline_and_the_last_phase() -> None:
    for scenario in load_all():
        assert scenario.total_seconds > scenario.baseline_seconds
        assert scenario.total_seconds == scenario.baseline_seconds + max(
            phase.end_seconds for phase in scenario.phases
        )


# --- the run loop ------------------------------------------------------------


def _offline_runner(monkeypatch: pytest.MonkeyPatch, **kwargs: Any) -> ScenarioRunner:
    runner = ScenarioRunner(tick_seconds=kwargs.pop("tick_seconds", 600.0), **kwargs)
    monkeypatch.setattr(runner.metrics, "push", lambda *a, **k: None)
    monkeypatch.setattr(runner.logs, "baseline_lines", lambda *a, **k: [])
    monkeypatch.setattr(runner.logs, "phase_lines", lambda *a, **k: [])
    monkeypatch.setattr(runner.logs, "push", lambda *a, **k: 0)
    return runner


def test_a_run_enters_every_phase_and_reports_them_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    runner = _offline_runner(monkeypatch, on_event=events.append)
    monkeypatch.setattr(runner.pipelines, "send_pipeline", lambda *a, **k: None)

    report = runner.run(load("bad_deploy_5xx"), speed=1e9, send_pipelines=False)

    assert report.phases_entered == ["deploy_lands", "errors_spike", "pool_exhaustion"]
    assert report.fault_started_wall is not None
    assert report.simulated_seconds > 0
    assert any("phase started" in message for message in events)


def test_a_flaky_scenario_sends_pipeline_events(monkeypatch: pytest.MonkeyPatch) -> None:
    """CI-shaped scenarios must drive the webhook, not only metrics and logs."""
    sent: list[str] = []
    runner = _offline_runner(monkeypatch)
    monkeypatch.setattr(
        runner.pipelines,
        "send_pipeline",
        lambda *a, **k: sent.append(k.get("status", "?")),
    )

    report = runner.run(load("flaky_test_storm"), speed=1e9, send_pipelines=True)

    assert report.pipelines_sent > 0
    assert sent and set(sent) == {"failed"}


def test_a_baseline_run_injects_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = _offline_runner(monkeypatch)
    report = runner.baseline(speed=1e9, simulated_seconds=6000.0)
    assert report.scenario == "baseline"
    assert report.metrics_pushes > 0


def test_falling_behind_is_announced(monkeypatch: pytest.MonkeyPatch) -> None:
    """Silence is the failure mode; the shortfall has to be said out loud."""
    events: list[str] = []
    runner = _offline_runner(monkeypatch, tick_seconds=1.0, on_event=events.append)
    # 1e9x with 1-second ticks cannot be met by any machine.
    report = runner.baseline(speed=1e9, simulated_seconds=30.0)

    assert not report.kept_up
    assert any("fell behind" in message for message in events), events


# --- CLI ---------------------------------------------------------------------


def test_cli_list_names_every_scenario_and_its_expected_answer() -> None:
    result = runner_cli.invoke(app, ["list"])
    assert result.exit_code == 0
    for scenario in load_all():
        assert scenario.name in result.stdout
        assert scenario.expected_root_cause.category.value in result.stdout


def test_cli_run_reports_what_it_produced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "simulator.cli.ScenarioRunner",
        lambda **_kwargs: _FakeRunner(),
    )
    result = runner_cli.invoke(app, ["run", "bad_deploy_5xx", "--speed", "1000"])
    assert result.exit_code == 0, result.stdout
    assert "Bad deploy" in result.stdout
    assert "ticks" in result.stdout


def test_cli_rejects_an_unknown_scenario_with_a_distinct_exit_code() -> None:
    result = runner_cli.invoke(app, ["run", "not_a_scenario"])
    assert result.exit_code == 2
    assert "not_a_scenario" in result.output


def test_cli_reports_a_failed_run_rather_than_pretending_it_worked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Exploding:
        def run(self, *args: Any, **kwargs: Any) -> None:
            raise httpx.ConnectError("pushgateway refused the connection")

    monkeypatch.setattr("simulator.cli.ScenarioRunner", lambda **_kwargs: Exploding())
    result = runner_cli.invoke(app, ["run", "bad_deploy_5xx"])
    assert result.exit_code == 1
    assert "run failed" in result.output


def test_cli_baseline_runs_and_summarises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("simulator.cli.ScenarioRunner", lambda **_kwargs: _FakeRunner())
    result = runner_cli.invoke(app, ["baseline", "--minutes", "0.1", "--speed", "500"])
    assert result.exit_code == 0
    assert "pushes" in result.stdout


class _FakeRunner:
    """Stands in for ScenarioRunner so the CLI can be tested without a stack."""

    def run(self, scenario: Any, **_kwargs: Any) -> Any:
        return self._report(scenario.name)

    def baseline(self, **_kwargs: Any) -> Any:
        return self._report("baseline")

    @staticmethod
    def _report(name: str) -> Any:
        from simulator.runner import RunReport

        return RunReport(
            scenario=name,
            speed=1000.0,
            ticks=12,
            metrics_pushes=12,
            log_lines=340,
            wall_seconds=1.5,
            achieved_speed=1000.0,
            phases_entered=["deploy_lands"],
        )


# --- the paths that only run when something goes wrong -----------------------


def test_node_disk_responds_to_a_phase_that_fills_it() -> None:
    """disk_pressure targets a node, so the deviation resolves through its pods."""
    generator = MetricsGenerator()
    node = NODES_BY_NAME["node-a"]
    phase = Phase(
        name="fills",
        start_seconds=0.0,
        duration_seconds=1000.0,
        target="node-a",
        deviations=[Deviation(metric=MetricName.DISK_USED, factor=2.5, shape=Shape.STEP)],
    )
    quiet = generator._node_disk(node, 500.0, [])
    filling = generator._node_disk(node, 500.0, [phase])
    assert filling > quiet, "a disk_used deviation on the node changed nothing"
    assert filling <= float(node.disk_bytes), "disk exceeded the node's capacity"


def test_a_phase_targeting_another_node_leaves_this_one_alone() -> None:
    generator = MetricsGenerator()
    phase = Phase(
        name="fills",
        start_seconds=0.0,
        duration_seconds=1000.0,
        target="node-c",
        deviations=[Deviation(metric=MetricName.DISK_USED, factor=2.5, shape=Shape.STEP)],
    )
    node = NODES_BY_NAME["node-a"]
    assert generator._node_disk(node, 500.0, [phase]) == generator._node_disk(node, 500.0, [])


def test_push_without_a_client_falls_back_to_the_library(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The library call is the standalone path; it must still be wired up."""
    called: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "simulator.metrics_generator.push_to_gateway",
        lambda gateway, job, registry: called.append({"gateway": gateway, "job": job}),
    )
    MetricsGenerator().push(0.0, [], 60.0)
    assert called == [{"gateway": "localhost:9091", "job": "pantheon-sim"}]


def test_a_gateway_url_with_a_scheme_is_not_double_prefixed() -> None:
    assert MetricsGenerator(gateway="http://pushgateway:9091")._gateway_url == (
        "http://pushgateway:9091"
    )
    assert MetricsGenerator(gateway="pushgateway:9091")._gateway_url == "http://pushgateway:9091"


def test_a_table_with_a_gap_is_refused_at_import() -> None:
    """Exercises the real invariant, not a copy of it written in the test.

    `require_every_metric` runs at import against both tables. Calling it here
    with a member removed proves the check works; asserting the source contains
    a `raise` would be satisfied by a comment.
    """
    incomplete = dict(NOISE_TABLE)
    incomplete.pop(MetricName.RESTARTS)

    with pytest.raises(RuntimeError, match="restarts"):
        require_every_metric("NOISE", incomplete)

    # And it must stay quiet on a complete table, or it would be unfailable in
    # the other direction.
    require_every_metric("NOISE", dict(NOISE_TABLE))


def test_cli_run_reports_an_interrupt_with_the_conventional_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """130 is what a shell expects from Ctrl-C; 0 would look like success."""

    class Interrupted:
        def run(self, *args: Any, **kwargs: Any) -> None:
            raise KeyboardInterrupt

        def baseline(self, *args: Any, **kwargs: Any) -> None:
            raise KeyboardInterrupt

    monkeypatch.setattr("simulator.cli.ScenarioRunner", lambda **_kwargs: Interrupted())
    assert runner_cli.invoke(app, ["run", "bad_deploy_5xx"]).exit_code == 130
    assert runner_cli.invoke(app, ["baseline"]).exit_code == 130


def test_cli_echo_indents_progress_lines(capsys: pytest.CaptureFixture[str]) -> None:
    """The runner reports phase changes through this, under the run banner."""
    from simulator.cli import _echo

    _echo("phase started: errors_spike")
    printed = capsys.readouterr().out
    assert printed.startswith("  "), f"progress line is not indented: {printed!r}"
    assert "errors_spike" in printed


def test_console_script_entrypoint_exists() -> None:
    """`pantheon-sim` resolves to this; a rename would break the installed script."""
    from simulator.cli import main

    result = runner_cli.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert callable(main)
