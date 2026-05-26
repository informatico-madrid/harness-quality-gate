"""Concurrency resolver: parallel / sequential / auto with CI auto-detection."""

from collections.abc import Mapping

from .models import ConcurrencyPlan

_CI_ENV_VARS = ("CI", "GITHUB_ACTIONS", "GITLAB_CI", "BUILDKITE", "CIRCLECI")


def resolve(mode: str, env: Mapping) -> ConcurrencyPlan:
    """Resolve the concurrency plan for a given mode and environment.

    Rules (priority order):
      1. ``mode="parallel"`` always wins — no CI check needed.
      2. ``mode="sequential"`` always returns sequential.
      3. ``mode="auto"`` defers to CI-env detection: if *any* CI env var
         is present the result is sequential; otherwise parallel.
    """

    # --- explicit modes --------------------------------------------------
    if mode == "parallel":
        return ConcurrencyPlan(mode="parallel", ci_detected=False, max_threads=1)

    if mode == "sequential":
        return ConcurrencyPlan(mode="sequential", ci_detected=False, max_threads=1)

    # --- auto mode -------------------------------------------------------
    ci_detected = any(env.get(k) for k in _CI_ENV_VARS)

    if ci_detected:
        return ConcurrencyPlan(mode="sequential", ci_detected=True, max_threads=1)

    return ConcurrencyPlan(mode="parallel", ci_detected=False, max_threads=1)
