# ChainOps evaluation (offline mode)

Generated 2026-10-19 22:49 UTC by `python evals/run_evals.py --llm offline`. Each scenario ran on a fresh seed database.

| Metric | Result |
|---|---|
| Scenarios passed | 18/18 (100%) |
| Risk classification | 5/5 (100%) |
| Decision agreement with expected outcome | 10/10 (100%) |
| Human-approval routing | 10/10 (100%) |
| Validation enforcement (invalid input stopped before agents) | 4/4 (100%) |
| Structured output validity (runs without injected faults) | 50/50 (100%) |
| LLM vs rule disagreements (runs without injected faults) | 0 |
| Coordinator chose a non-default supplier (runs without injected faults) | 0 |
| Injected faults detected | 3/3 (100%) |
| Workflow completion | 17/17 (100%) |
| Crashed scenarios | 0 |
| Grounded coordinator explanations (mention actual stock) | 12/13 (92%) |
| Cycle latency p50 / max | 12 ms / 124 ms |

| ID | Scenario | Category | Result | Failed checks |
|---|---|---|---|---|
| S01 | Normal inventory, stable demand | baseline | PASS |  |
| S02 | Demand spike with insufficient inventory | event_trigger | PASS |  |
| S03 | Supplier delay affecting a critical, low-stock product | event_trigger | PASS |  |
| S04 | Invalid inventory data (negative stock) | data_validation | PASS |  |
| S05 | Malformed event payload (schema) | data_validation | PASS |  |
| S06 | High-risk replenishment above the order ceiling | governance | PASS |  |
| S07 | Conflicting signals (risk HIGH, stock sufficient) | conflict_resolution | PASS |  |
| S08 | High-risk recommendation approved by a human | governance | PASS |  |
| S09 | High-risk recommendation rejected by a human | governance | PASS |  |
| S10 | Malformed coordinator output | ai_output_validation | PASS |  |
| S11 | LLM unavailable for every agent (recovery via rule fallback) | failure_recovery | PASS |  |
| S12 | Unsafe LLM answers cannot bypass approval | ai_output_validation | PASS |  |
| S13 | Duplicate event delivery (webhook retry) | idempotency | PASS |  |
| S14 | Execution failure, then successful retry | failure_recovery | PASS |  |
| S15 | Stale event | data_validation | PASS |  |
| S16 | Event below trigger threshold | event_trigger | PASS |  |
| S17 | Inconsistent reference (shipment of another product) | data_validation | PASS |  |
| S18 | Double approval does not create a second order | idempotency | PASS |  |
