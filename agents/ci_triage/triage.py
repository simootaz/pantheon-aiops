"""Separating a flake from a regression, and refusing to guess between them.

A FLAKE HAS A DEFINITION, NOT A HEURISTIC
------------------------------------------
A job is flaky when it produces two different outcomes **from the same input**.
That is what non-determinism means, and CI hands us the input as a commit sha:
the same job name, at the same `head_sha`, succeeding in one run and failing in
another is a flake by definition.

That matters because every other available signal is a guess. "The test name
contains `flaky`" is a name heuristic - the exact thing
`tests/unit/test_connectors.py` exists to stop anyone relying on. "It failed at
a different step" is consistent with a real race and with a real bug. "It fails
often" is a statement about how often somebody pushed.

THE HONEST ANSWER TO ONE OBSERVATION IS UNKNOWN
-------------------------------------------------
A job that failed once, at one commit, with no retry, is not classifiable. It
could be a flake nobody has re-run yet or a regression the change introduced,
and nothing distinguishes them from a single result.

That is most CI failures, and it is reported as `UNKNOWN` rather than guessed
at. A triage agent that labelled every first failure would be right about half
of them and trusted for neither.

WHAT WOULD MAKE `REGRESSION` STATABLE, AND WHY IT IS NOT HERE
--------------------------------------------------------------
A job that fails at this commit and passed at its parent is a regression the
change introduced. That needs the parent's runs, which needs the parent sha -
carried by the commits API, which this connector does not reach.

Named rather than half-built: a `REGRESSION` verdict derived from anything less
would be `UNKNOWN` wearing a stronger word.

Phase: 4 - Delivery Flow
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum

#: Conclusions that mean the job ran and did not pass. `cancelled` and `skipped`
#: are NOT failures: a cancelled job says somebody pushed again, and counting it
#: as a failure would make every force-push look like a broken test.
FAILED = frozenset({"failure", "timed_out"})

#: The one conclusion that means it ran and passed.
PASSED = "success"


class Verdict(StrEnum):
    """What can be said about one failing job."""

    #: The same job, at the same commit, both passed and failed. Definitional.
    FLAKE = "flake"
    #: It failed, and nothing here can say why. Most failures.
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class JobOutcome:
    """One job's result in one run."""

    name: str
    conclusion: str
    run_id: int
    attempt: int = 1

    @property
    def failed(self) -> bool:
        return self.conclusion in FAILED

    @property
    def passed(self) -> bool:
        return self.conclusion == PASSED


@dataclass
class Triage:
    """One failing job, and what the evidence supports about it."""

    job: str
    verdict: Verdict
    #: Every run at this commit in which the job finished, for the reader.
    attempts: list[JobOutcome] = field(default_factory=list)
    why: str = ""

    @property
    def flaky(self) -> bool:
        return self.verdict is Verdict.FLAKE


def classify(outcomes: list[JobOutcome]) -> list[Triage]:
    """Triage every job that failed at least once, at one commit.

    `outcomes` must all be from the same `head_sha` - the caller is responsible
    for that, because this function cannot check it and comparing across commits
    is how "this test is flaky" gets concluded from two different bugs.
    `agents/ci_triage/agent.py` is the caller, and it filters by sha.

    Jobs that only ever passed are not returned. A triage listing every green
    job is a triage nobody reads to the end.
    """
    by_job: dict[str, list[JobOutcome]] = defaultdict(list)
    for outcome in outcomes:
        by_job[outcome.name].append(outcome)

    triaged: list[Triage] = []
    for name in sorted(by_job):
        results = by_job[name]
        if not any(outcome.failed for outcome in results):
            continue
        triaged.append(_one(name, results))
    return triaged


def _one(name: str, results: list[JobOutcome]) -> Triage:
    """The verdict for one job's results at one commit."""
    passes = [outcome for outcome in results if outcome.passed]
    failures = [outcome for outcome in results if outcome.failed]

    if passes and failures:
        return Triage(
            job=name,
            verdict=Verdict.FLAKE,
            attempts=results,
            why=(
                f"{name} both passed and failed at this commit "
                f"({len(passes)} passed, {len(failures)} failed). The same job on the "
                "same input finishing two different ways is non-determinism by "
                "definition, not an inference from it."
            ),
        )

    return Triage(
        job=name,
        verdict=Verdict.UNKNOWN,
        attempts=results,
        why=(
            f"{name} failed {len(failures)} time(s) at this commit and never passed "
            "here, so nothing distinguishes a flake nobody has re-run from a "
            "regression the change introduced. Re-running it at this commit is what "
            "would answer the question."
        ),
    )


def outcomes_from(
    runs: list[dict[str, object]], jobs_by_run: dict[int, list[dict[str, object]]]
) -> list[JobOutcome]:
    """Flatten GitHub's shapes into `JobOutcome`s.

    A job with no `conclusion` is still running or queued and is dropped: it has
    not produced an outcome, and treating an absent conclusion as a failure
    would make every in-progress pipeline look broken.
    """
    flattened: list[JobOutcome] = []
    for run in runs:
        run_id = run.get("id")
        if not isinstance(run_id, int):
            continue
        for job in jobs_by_run.get(run_id, []):
            name, conclusion = job.get("name"), job.get("conclusion")
            if not isinstance(name, str) or not isinstance(conclusion, str):
                continue
            attempt = job.get("run_attempt")
            flattened.append(
                JobOutcome(
                    name=name,
                    conclusion=conclusion,
                    run_id=run_id,
                    attempt=attempt if isinstance(attempt, int) else 1,
                )
            )
    return flattened
