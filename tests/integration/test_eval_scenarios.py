"""Every scenario in evals/scenarios.json must pass in offline mode."""

import pytest

from run_evals import load_scenarios, run_scenario

SCENARIOS = load_scenarios()


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s["id"] for s in SCENARIOS])
def test_scenario(scenario):
    result = run_scenario(scenario)
    failed = [f"{c['check']} ({c['detail']})" for c in result["checks"] if not c["passed"]]
    assert result["passed"], f"{scenario['id']} {scenario['name']}: {failed}"
