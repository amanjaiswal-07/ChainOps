# ChainOps: Upgrade Summary

What was delivered in the upgrade of the original *Multi-Agent Supply Chain Control Tower*, where it lives, and how it was verified. The [README](../README.md) explains the system; the [audit](AUDIT.md) records the starting point.

## 1. Starting point

The original project already had five LangGraph agents, a deterministic decision gate and a Streamlit page. The audit found four serious gaps:

* **Fake human approval.** The approval node hard-coded `"APPROVED"`, so every high-risk order executed with no human involved.
* **No data validation.** Negative stock, missing rows or broken references went straight to the LLM; a missing inventory row crashed the run.
* **Fail-open LLM parsing.** Anything that was not literally "HIGH" became "LOW", and the coordinator could invent suppliers and quantities.
* **Startup and API-key failures.** The database path depended on the working directory, seeding crashed on Windows consoles, and without an API key the run died with a raw traceback.

## 2. Deliverables

| # | Deliverable | Where | Verified by |
|---|---|---|---|
| 1 | Baseline audit with workflow trace and audit table | `docs/AUDIT.md` | Baseline runs recorded in the document |
| 2 | Event-driven workflow: 3 event types, trigger thresholds, idempotent `event_id` | `src/events.py`, `src/workflow.py` | `tests/unit/test_events.py`, `tests/integration/test_workflow.py`, live API run |
| 3 | FastAPI layer (9 endpoints, 413 / 409 / 422 / 503 handling, no stack traces) | `src/api.py` | `tests/integration/test_api.py`, real uvicorn server |
| 4 | Automated triggering demo: webhook sender and scheduled scanner | `scripts/event_simulator.py` | Run against the live API; output in the README |
| 5 | Data validation before any agent runs (business rules, errors vs warnings) | `src/validation.py`, `src/nodes/data_validation.py` | `tests/unit/test_validation.py` |
| 6 | AI-output validation: strict parsers, Pydantic models, rule-baseline cross-check | `src/agents/outputs.py`, `src/agents/rules.py` | `tests/unit/test_agent_outputs.py`, eval S10 to S12 |
| 7 | Explicit approval policy (8 rules) with recorded reasons | `src/nodes/decision_gate.py` | `tests/unit/test_rules_and_policy.py` |
| 8 | Governance state machine: compare-and-set transitions, transactional execution, retry | `src/governance.py` | `tests/unit/test_governance.py`, including a 5-thread concurrency test |
| 9 | Decision audit records (input, validation, agent trace, outputs, risk reasons, review, execution, errors) | `src/models.py` (`DecisionRecord`) | API `GET /decisions/{id}`, UI audit tab |
| 10 | Scenario simulator and approvals/audit tabs in Streamlit | `ui/app.py`, `src/scenarios.py` | Driven in a browser; screenshots in `docs/screenshots/` |
| 11 | Offline mode (rule baselines, labelled) and live mode with timeouts and bounded retries | `src/llm_config.py`, `src/config.py` | Offline suite; live suite with OpenRouter |
| 12 | Evaluation framework: 18 scenarios, fault injection, metrics report | `evals/` | `evals/results/latest_offline.md`, `evals/results/latest_live.md` |
| 13 | Test suite: 86 unit, 57 integration, 2 live | `tests/` | `pytest` (143 passed), `pytest -m live` (2 passed) |
| 14 | Structured JSON logging | `src/logging_config.py` | API server log |
| 15 | Reproducible setup: pinned versions, `.env.example`, absolute DB path | `requirements.txt`, `.env.example` | Fresh clone, fresh venv, tests pass |
| 16 | README with architecture, workflows, API examples, results and screenshots | `README.md` | Every number taken from an executed run |

## 3. Measured results

| | Offline | Live (`openai/gpt-4o-mini`, 3 runs) |
|---|---|---|
| Evaluation scenarios | 18/18 | 18/18 in every run |
| Structured output validity (no injected faults) | 50/50 | 50/50 in every run |
| LLM vs rule disagreements | n/a | 0 in every run |
| Coordinator chose a non-default supplier | n/a | 1, 2, 1 of 10 decisions |
| Cycle latency p50 | 12 ms | about 11 to 12 s |
| Offline pytest suite | 143 passed | |
| Live pytest suite | | 2 passed |

LangSmith tracing was checked: each decision cycle appears as a `LangGraph` run with the agent calls nested inside.

## 4. Findings from live testing

* **Supplier choice.** The coordinator sometimes chose an 85% reliable supplier over the 95% one with weak reasoning. This was valid under its prompt but invisible to reviewers, so it became rule 8 of the approval policy.
* **Incomplete explanations.** Explanations can be correct but incomplete. Only structured fields and one grounding criterion are checked automatically.

## 5. Removed

* `src/nodes/execution.py`: side effects moved out of the graph into `governance.py`.
* `create_continuous_monitoring_graph`: it looped forever; replaced by the event scanner.
* `ui/arch_diagram.png`: showed an agent that does not exist; replaced by Mermaid diagrams.
* `demo/demo.py`: static page with hard-coded output; the real UI now runs without an API key.
* `ui/helpers.py`: unused.
* Dead code: duplicate functions, about 150 lines of commented-out code, and debug-log instrumentation.

## 6. Left as documented decisions

These are business-rule choices, kept as the original project defined them and listed under Known limitations in the README:

* **Every REORDER is high risk,** so nothing is auto-approved.
* **Open purchase orders are not counted as stock.**
* **Supplier risk is global:** it is set by the weakest supplier, even one that is never chosen.

Also out of scope: authentication (the reviewer name is not verified), real ERP integration (execution is simulated), and live evaluation of models other than gpt-4o-mini.

## 7. Commit history

1. Original code, unchanged, imported as the baseline
2. Startup fixes, configuration, pinned dependencies, LLM modes
3. Validation before agents and validation of AI outputs after them
4. Governance state machine, event pipeline, FastAPI layer
5. Streamlit scenario simulator and approvals/audit tab
6. Test suite and evaluation framework
7. README, audit, screenshots
8. README additions: executed-decision screenshot, workflows, walkthrough, author
9. Live LLM evaluation and approval rule 8
10. This cleanup and summary
