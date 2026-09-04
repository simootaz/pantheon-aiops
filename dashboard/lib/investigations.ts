/**
 * Reading an Investigation: the questions a list row asks.
 *
 * Pure functions over the contract, kept out of the components so they can be
 * tested without rendering anything - and so the definitions live in one place
 * rather than being re-derived slightly differently in each view.
 *
 * WHY `isPartial` IS NOT A FIELD
 * ------------------------------
 * `InvestigationCompletedEvent` carries a `partial` flag, but the Investigation
 * itself does not, and adding one to the contract would create a second thing
 * that can be wrong. Partiality is not a claim the orchestrator makes; it IS a
 * DEGRADED Finding being present - that kind exists precisely so an agent that
 * could not do its job says so on the record, instead of returning nothing and
 * looking like an agent that found nothing.
 *
 * So this reads the findings. A run whose Lethe step lost its lease is partial
 * because the degraded finding is there, and it stays partial no matter what
 * any flag elsewhere says.
 *
 * Phase: 4 - Delivery Flow
 */
import type { Finding, Investigation } from "@/types/generated/contracts";

/** The findings that say an agent could not do its job. */
export function degraded(investigation: Investigation): Finding[] {
  return (investigation.findings ?? []).filter((finding) => finding.kind === "degraded");
}

/**
 * Whether some part of this run did not happen.
 *
 * The difference between "nobody found anything" and "nobody looked", which is
 * the whole reason the DEGRADED kind exists. A reader shown a confident verdict
 * from a run that never reached its logs is being misled by omission.
 */
export function isPartial(investigation: Investigation): boolean {
  return degraded(investigation).length > 0;
}

/** Whether the run has stopped, either way. */
export function isTerminal(investigation: Investigation): boolean {
  return (
    investigation.state === "completed" ||
    investigation.state === "failed" ||
    investigation.state === "cancelled"
  );
}

/**
 * The headline for one run.
 *
 * The trigger's title when it has one, and the id when it does not. Never an
 * empty string: a row with no visible text is a row nobody can click on
 * purpose.
 */
export function headline(investigation: Investigation): string {
  const title = investigation.trigger?.title;
  return title !== null && title !== undefined && title.trim() !== "" ? title : investigation.id;
}
