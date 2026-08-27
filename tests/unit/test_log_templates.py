"""What the templater does, and what it refuses to claim.

These assert *behaviour*, on lines written here rather than drawn from the
simulator. The parameters themselves are settled by measurement - see
docs/lethe-predictions/ - and asserting a template COUNT here would bake this
run's numbers into a test that then has to be edited whenever the measurement
says something different, which is how a calibration stops being one.

Phase: 2 - Orchestrator & Investigation Flow
"""

from __future__ import annotations

import json

import pytest

from agents.log_clustering.templates import (
    MIN_GROUP_FOR_VARIABILITY,
    Clustering,
    cluster,
    compare,
    learn,
    novel,
    stack_traces,
)


def _requests(count: int, *, status: int = 200, path: str = "/api/cart") -> list[str]:
    """Lines that differ only in fields a corpus can see are variable."""
    return [
        json.dumps(
            {
                "ts": f"2026-08-27T10:{index // 60:02d}:{index % 60:02d}Z",
                "level": "info",
                "msg": "request completed",
                "path": path,
                "status": status,
                "duration_ms": 40 + index,
            }
        )
        for index in range(count)
    ]


def _enough() -> int:
    """Comfortably above the group floor, so these tests are about the rule."""
    return MIN_GROUP_FOR_VARIABILITY * 4


# --- the thing it is for --------------------------------------------------------


def test_lines_differing_only_in_variable_fields_are_one_template() -> None:
    """The whole point. `ts` and `duration_ms` differ on every line."""
    result = cluster(_requests(_enough()))

    assert len(result.templates) == 1, (
        f"one template expected, got {[t.rendered for t in result.templates]}"
    )
    template = result.templates[0]
    assert template.count == _enough()
    assert template.inferred, "a group this size should have inferred its variable fields"
    assert "msg=request completed" in template.rendered
    assert "ts=<*>" in template.rendered, "ts was kept in the template rather than masked"
    assert "duration_ms=<*>" in template.rendered


def test_a_discriminating_field_splits_the_template() -> None:
    """`status` takes two values across many lines, so it is not noise."""
    lines = _requests(_enough(), status=200) + _requests(_enough(), status=500)
    result = cluster(lines)

    assert len(result.templates) == 2, (
        "a two-valued field was masked away, so a 500 and a 200 read as the same event"
    )
    assert {template.count for template in result.templates} == {_enough()}


def test_a_high_cardinality_field_does_not_split_the_template() -> None:
    """The control for the test above.

    Without it, "splits on a field" would be satisfied by an implementation that
    splits on every field - which is one template per line and no clustering.
    """
    lines = [
        json.dumps({"msg": "request completed", "request_id": f"req-{index}", "level": "info"})
        for index in range(_enough())
    ]
    result = cluster(lines)

    assert len(result.templates) == 1, (
        "a unique-per-line field became part of the template, so every line is its own cluster"
    )


def test_different_field_sets_are_never_the_same_template() -> None:
    """Shape first. Two lines with different keys describe different events."""
    lines = _requests(_enough()) + [
        json.dumps({"ts": "t", "level": "warn", "msg": "GC pause exceeded target", "pause_ms": p})
        for p in range(_enough())
    ]
    result = cluster(lines)

    assert len(result.templates) == 2
    assert {t.rendered.split("=")[0] for t in result.templates}  # both rendered


# --- what it refuses ------------------------------------------------------------


def test_a_group_too_small_to_template_says_so_rather_than_guessing() -> None:
    """Three lines make every field look stable.

    A template set that changes shape as the fourth line arrives is not a
    template set, so the group is reported by shape and `inferred` is False.
    """
    result = cluster(_requests(MIN_GROUP_FOR_VARIABILITY - 1))

    assert len(result.templates) == 1
    template = result.templates[0]
    assert template.shape_only, "a group under the floor claimed to know its variable fields"
    assert not template.inferred
    assert "too few lines" in template.rendered


def test_the_floor_is_a_floor_and_not_a_ceiling() -> None:
    """The control. A group AT the floor must template normally, or the refusal
    above would be indistinguishable from an implementation that never templates."""
    result = cluster(_requests(MIN_GROUP_FOR_VARIABILITY))

    assert result.templates[0].inferred
    assert not result.templates[0].shape_only


def test_a_shape_only_template_is_never_reported_as_novel() -> None:
    """ "This shape is new" fires whenever a window happens to contain a handful
    of lines of a kind the reference had many of - a statement about window size
    wearing the costume of a finding."""
    reference = cluster(_requests(_enough()))
    incident = cluster(
        _requests(_enough())
        + [json.dumps({"msg": "disk usage high", "used_percent": p}) for p in range(3)]
    )

    assert any(t.shape_only for t in incident.templates), "the fixture stopped exercising this"
    assert novel(incident, reference) == [], (
        "a three-line shape-only group was reported as a novel pattern"
    )


def test_a_real_new_template_is_reported_as_novel() -> None:
    """The control for the refusal above."""
    reference = cluster(_requests(_enough()))
    incident = cluster(
        _requests(_enough())
        + [json.dumps({"msg": "disk usage high", "used_percent": p}) for p in range(_enough())]
    )

    fresh = novel(incident, reference)
    assert len(fresh) == 1
    assert "disk usage high" in fresh[0].rendered


def test_two_identical_windows_produce_no_novelty() -> None:
    """The zero case. A novelty rule that fires on an unchanged window is noise."""
    lines = _requests(_enough())
    assert novel(cluster(lines), cluster(lines)) == []


def test_an_unparsable_line_is_counted_rather_than_dropped() -> None:
    """Silently dropping lines makes a window look quieter than it was."""
    result = cluster(["", "   ", *_requests(_enough())])
    assert result.unparsed == 2
    assert result.lines_seen == _enough()


def test_a_line_that_is_not_json_still_templates() -> None:
    """Text lines fall back to positional tokens and the same counting.

    Asserted because the fallback is the path the simulator never exercises -
    every line it writes is JSON - and an unexercised path is one that works
    until the first system that logs plain text.
    """
    lines = [f"2026-08-27T10:00:{i:02d}Z INFO worker finished job {i}" for i in range(_enough())]
    result = cluster(lines)

    assert len(result.templates) == 1, (
        f"plain text lines did not cluster: {[t.rendered for t in result.templates]}"
    )
    assert result.templates[0].inferred


def test_malformed_json_is_treated_as_text_not_discarded() -> None:
    """A truncated line is still evidence that something logged."""
    lines = [f'{{"msg": "truncated at {i}' for i in range(_enough())]
    result = cluster(lines)

    assert result.unparsed == 0
    assert result.lines_seen == _enough()


# --- stack traces ---------------------------------------------------------------


def _trace(line_number: int) -> str:
    return json.dumps(
        {
            "level": "error",
            "msg": "unhandled exception",
            "exception": "java.lang.OutOfMemoryError: Java heap space",
            "stack": (
                f"at com.acme.checkout.Handler.process(Handler.java:{line_number})\n"
                f"\tat com.acme.checkout.Router.dispatch(Router.java:{line_number + 7})\n"
                "\tat java.base/java.lang.Thread.run(Thread.java:840)"
            ),
        }
    )


def test_the_same_fault_at_different_line_numbers_is_one_trace() -> None:
    """Digits are masked before grouping, or a fault becomes one trace per throw."""
    traces = stack_traces([_trace(number) for number in range(100, 140)])

    assert len(traces) == 1, f"{len(traces)} signatures for one fault"
    assert traces[0].count == 40
    assert traces[0].header == "java.lang.OutOfMemoryError: Java heap space", (
        "the header was paraphrased or taken from the wrong field"
    )
    assert len(traces[0].frames) == 3


def test_two_different_faults_stay_two_traces() -> None:
    """The control. Masking that collapses everything proves nothing above."""
    other = json.dumps(
        {
            "level": "error",
            "msg": "unhandled exception",
            "exception": "java.lang.NullPointerException: null",
            "stack": (
                "at com.acme.cart.Totals.sum(Totals.java:12)\n"
                "\tat com.acme.cart.Api.handle(Api.java:44)"
            ),
        }
    )
    traces = stack_traces([_trace(100), _trace(101), other])
    assert len(traces) == 2


def test_a_language_this_matcher_never_heard_of_still_groups() -> None:
    """No language is named in the matcher.

    One that listed Java and Python would pass silently over Go, and passing
    over is indistinguishable from finding nothing.
    """
    lines = [
        json.dumps(
            {
                "level": "error",
                "err": "runtime error: index out of range",
                "goroutine": (
                    f"main.process(0x{index:x})\n\tmain.handle(0x{index + 1:x})\n\tmain.main()"
                ),
            }
        )
        for index in range(20)
    ]
    traces = stack_traces(lines)
    assert len(traces) == 1, f"Go-style frames produced {len(traces)} signatures"
    assert traces[0].count == 20


def test_a_multi_line_value_that_is_not_a_stack_is_not_reported() -> None:
    """Frames share a leading token; a wrapped message does not."""
    lines = [
        json.dumps({"msg": "notice", "body": "first line here\nentirely different second\nthird"})
        for _ in range(20)
    ]
    assert stack_traces(lines) == []


@pytest.mark.parametrize("lines", [[], [""], ["not json at all"]])
def test_an_empty_or_useless_window_produces_nothing_rather_than_failing(
    lines: list[str],
) -> None:
    """A quiet window is a result. Raising here would make silence an error."""
    result = cluster(lines)
    assert isinstance(result, Clustering)
    assert stack_traces(lines) == []


# --- absence has to be surprising, not merely absent -----------------------------


def _rare(count: int) -> list[str]:
    """A group large enough to template, so the surprise test is what decides."""
    return [json.dumps({"msg": "occasional", "n": index}) for index in range(count)]


def test_a_template_too_rare_for_its_absence_to_mean_anything_is_not_novel() -> None:
    """Measured: nineteen novel templates for one disk fault, eighteen of them
    `request failed` variants at count one or two.

    Those are not new events. They are combinations the reference happened not
    to contain, and a longer reference would have contained them.
    """
    incident = cluster(_requests(4000) + _rare(MIN_GROUP_FOR_VARIABILITY))
    reference = cluster(_requests(800))

    assert any("occasional" in t.rendered for t in incident.templates), "fixture broken"
    assert not any(t.shape_only for t in incident.templates), (
        "the rare group fell under the shape-only floor, so the surprise test never ran"
    )
    assert novel(incident, reference) == []


def test_a_template_common_enough_for_its_absence_to_be_surprising_is_novel() -> None:
    """The control. A filter that rejected everything would pass the test above."""
    reference = cluster(_requests(2000))
    loud = [json.dumps({"msg": "disk usage high", "used_percent": p}) for p in range(60)]
    incident = cluster(_requests(2000) + loud)

    fresh = novel(incident, reference)
    assert len(fresh) == 1
    assert "disk usage high" in fresh[0].rendered


def test_the_bar_scales_with_the_reference_rather_than_being_a_fixed_count() -> None:
    """The reason this is a test and not a threshold.

    The SAME template at the SAME count is surprising against a long reference
    and unremarkable against a short one, because a short reference had little
    opportunity to contain it. A fixed minimum count cannot express that, and
    would be a number fitted to whatever window size it was chosen on.
    """
    incident = cluster(_requests(4000) + _rare(MIN_GROUP_FOR_VARIABILITY))

    assert novel(incident, cluster(_requests(800))) == [], (
        "12 lines in 4012 is not surprising in an 800-line reference"
    )
    assert len(novel(incident, cluster(_requests(4000)))) == 1, (
        "12 lines in 4012 IS surprising in a 4000-line reference"
    )


# --- one classification, shared between the windows being compared ---------------


def _coded(count: int) -> list[str]:
    """An event whose `code` field has five values, so how MANY of it a window
    holds decides whether that field survives the ratio rule."""
    return [json.dumps({"msg": "err", "code": index % 5, "n": index}) for index in range(count)]


def test_a_shared_classification_templates_the_same_event_the_same_way() -> None:
    """Measured, and the reason `compare()` exists.

    Variability is inferred from a group, so the group's SIZE changes the
    inference. Five `code` values among 500 lines are a category and split the
    event five ways; the same five among fifteen lines exceed the ratio and are
    masked into one. Diffing those two decompositions measures how much of the
    event each window held and reports it as novelty.
    """
    alone_many = cluster(_coded(500))
    alone_few = cluster(_coded(15))
    assert len(alone_many.templates) != len(alone_few.templates), (
        "the fixture no longer demonstrates size-dependent templating"
    )

    shared_few, shared_many = compare(_coded(15), _coded(500))
    err_few = {t.signature for t in shared_few.templates}
    err_many = {t.signature for t in shared_many.templates}

    assert err_few <= err_many, (
        "under one classification the smaller window's templates must be a "
        "subset of the larger's, not a different decomposition"
    )


def test_learning_on_one_corpus_and_applying_it_to_another_is_stable() -> None:
    """Two windows of the same traffic, templated identically."""
    classification = learn(_requests(400))
    left = cluster(_requests(200), classification)
    right = cluster(_requests(200), classification)

    assert left.signatures == right.signatures
    assert len(left.templates) == 1


def test_a_clean_window_compared_with_itself_reports_nothing_novel() -> None:
    """The zero case, through the whole `compare` path rather than by hand."""
    lines = _requests(_enough())
    incident, reference = compare(lines, lines)
    assert novel(incident, reference) == []
