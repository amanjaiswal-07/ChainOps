# ChainOps: Baseline Audit

Audit of the original *Multi-Agent Supply Chain Control Tower* code (commit `9d770fa`), done before any change was made. Everything below was checked by reading the code and running it on Windows 11 with Python 3.13.

## 1. How the original workflow ran

1. **Input.** The user picks product 1, 2 or 3 in Streamlit (`ui/app.py`) or runs `python -m src.main` (all three products). There was no API and no event input.
2. **Data load.** `data_ingestion_node` calls `db_service.read_supply_chain_snapshot(product_id)`, which reads product, inventory, all suppliers, the product's active POs and their in-transit shipments from SQLite.
3. **Validation.** None. If a product had no inventory row the code crashed with `AttributeError` on `None.quantity`. Negative stock, bad reliability scores or broken references flowed straight into the prompts.
4. **Agents** ran sequentially on a LangGraph `StateGraph`: demand, inventory, risk, logistics, coordinator. They share state through `agent_outputs`, which a reducer merges.
   - *Demand*: the LLM classifies LOW/HIGH using rules stated in the prompt.
   - *Inventory*: deterministic code (REORDER if qty < reorder point, quantity = 2 x ROP - qty). The LLM only writes the explanation.
   - *Risk*: the LLM classifies supplier risk (any reliability < 90%) and logistics risk (shipment > 7 days, overdue, or none).
   - *Logistics*: the LLM decides whether to expedite using three rules stated in the prompt.
   - *Coordinator*: the LLM picks decision type, supplier, quantity and expedite flag, returned as `KEY: value` text.
5. **Parsing.** Free text was parsed with substring checks. Anything that was not literally "HIGH" became "LOW" (fail-open), and the coordinator could return any supplier ID or quantity without a check.
6. **Risk gate.** `decision_gate_node` is deterministic: HIGH if any agent risk is HIGH or UNKNOWN, and every HOLD is downgraded to LOW.
7. **Human approval.** `human_approval_node` logged a request and then **hard-coded `simulated_feedback = "APPROVED"`**. Every high-risk decision was approved automatically and executed in the same run.
8. **Execution.** `execution_node` wrote a `PurchaseOrder` row and a `DecisionLog` row. There was no decision ID, no idempotency and no record of who approved what.
9. **Presentation.** Streamlit showed the snapshot, agent reasoning, final decision and three governance metrics. The "Approval Status" metric showed "APPROVED" for an approval no human gave.
10. **Real action or recommendation?** Executed immediately against the local SQLite DB. No external ERP.

## 2. Baseline run results

| Check | Result |
|---|---|
| `pip install -r requirements.txt` | OK (unpinned ranges, so resolved versions drift) |
| `compileall` on all `.py` | OK |
| `python -m src.main` | Starts, seeds, compiles the graph, then fails at the first LLM call without a valid key (HTTP 401 with a dummy key) |
| `db_init.seed_data` on a Windows console | Crashes with `UnicodeEncodeError` on the `→` character after commit |
| DB location | Relative to CWD: running from `src/` and from repo root used two different databases. Streamlit from root failed with `unable to open database file` unless `data/` already existed. |
| Decision cycle without `OPENROUTER_API_KEY` | Crashes inside the first agent with a raw OpenAI credentials traceback |
| Existing tests | None |

## 3. Audit table

| Area | Current implementation | Gap or limitation | Proposed change | Priority |
|---|---|---|---|---|
| Human approval | Node hard-codes `"APPROVED"` | High-risk orders execute with no human. Governance metric is misleading. | Real pause: the graph stops at `PENDING_APPROVAL`. Approve/reject by decision ID through API/UI, with enforced state transitions. | **P0** |
| Execution | PO written inside the graph run | Recommendation and execution are the same step. No idempotency, no failure state. | Execution moved to a governance service, allowed only from `APPROVED`/`AUTO_APPROVED`, atomic compare-and-set, PO and status in one transaction, `EXECUTION_FAILED` recorded separately | **P0** |
| Input data validation | None | Crashes on missing rows. Invalid data reaches the LLM and can produce orders. | Business-rule validation node before agents. Errors stop the graph, warnings force human review. | **P0** |
| AI output validation | Substring parsing, fail-open to LOW | Malformed LLM output looks "LOW risk". Coordinator can invent supplier IDs or quantities. | Strict parsing + Pydantic models. Deterministic rule baseline per agent. Fallback and disagreement are flagged and force approval. | **P0** |
| Event-driven triggers | None. Manual button or CLI only. | No way to react to business events | Pydantic event schema, trigger thresholds, idempotent `event_id`, FastAPI `POST /events`, webhook/scanner simulator | **P1** |
| API | `fastapi`/`uvicorn` in requirements but no API code | | Small FastAPI app: health, events, decision cycles, decision lookup, approve/reject/retry | **P1** |
| Audit trail | `decision_log` free-text rows. `ApprovalQueue` model defined but never used. | Cannot reconstruct why a decision happened | `decision_records` table: input, validation report, agent sequence and timings, outputs, risk reasons, approval, execution, errors | **P1** |
| Evaluation | None | No evidence the workflow behaves correctly | Scenario dataset + runner + pytest unit/integration tests with mocked LLM | **P1** |
| LLM config | No timeout, no retry limit, raw crash without key | | Timeout + bounded retries. Clear error in `live` mode. Labelled rule-based `offline` mode so the system runs and is testable without a key. | **P1** |
| Scenario simulator (UI) | README lists it as a "next step". `demo/demo.py` is hard-coded screens. | | Simulator tab that applies scenario overlays and runs the real graph, with baseline vs scenario comparison. `demo/demo.py` and the unused `ui/helpers.py` were removed afterwards. | **P2** |
| Continuous monitoring graph | `create_continuous_monitoring_graph` loops `execute → ingest` forever with no exit | Unusable; it would also re-order on every loop | Replaced with an explicit scanner that raises events | **P2** |
| DB path / startup | CWD-relative path, Unicode crash on Windows consoles | Fresh setup fails depending on where you run it | Absolute default path, ASCII console output | **P1** |
| Dead code | Duplicate `read_supply_chain_snapshot`, duplicate `human_approval_node` in `execution.py`, 150 lines of commented "production" code, `.cursor/debug.log` instrumentation in `backend_interface.py` | Confusing to read | Remove | **P2** |
| Dependencies | Unpinned ranges, Streamlit not listed | Not reproducible | Pin the versions that were tested | **P2** |
| Architecture diagram | PNG shows a "Procurement Agent" that does not exist | Misleading | Mermaid diagram matching the real graph | **P2** |
| `.gitignore` | `.env.*` also ignores `.env.example` | Example config never committed | Add `!.env.example` | **P2** |

## 4. Business-rule findings (kept as-is, documented)

These came out of running the workflow. Changing them would change business behaviour, so they are left as they were and listed here and in the README.

- **Every REORDER is HIGH risk.** The demand agent flags HIGH whenever stock is below the reorder point, and that is exactly the condition that makes the inventory agent REORDER. So under the original rules no order is ever auto-approved; the `AUTO_APPROVED` path is covered by unit tests with constructed state.
- **Open purchase orders are not counted as stock.** The inventory rule compares on-hand stock only. Approving an order and re-running the cycle recommends ordering again. An inventory-position rule (on hand + on order) would fix this but is a business decision.
- **Supplier risk is global.** It is HIGH if *any* supplier is below 90%, even one that is never selected. The seed data has two such suppliers, so supplier risk is always HIGH.

## 5. Deliberately not added

- **RAG / vector DB.** The agents reason over structured rows. There is no document corpus (contracts, SOPs) to retrieve from, and InsightAI already covers RAG.
- **MCP server.** The REST API already exposes the tools. An MCP wrapper would add no capability the project uses.
- **Task queue / Kafka.** One-product decision cycles finish in seconds. The API runs them in the request and says so.
- **Forecasting model.** There is no demand history in the data model. Demand spikes are modelled as a scaled reorder point (see README).
- **Authentication.** Out of scope for a local prototype. The approver name is recorded but not verified, and this is listed as a limitation.
