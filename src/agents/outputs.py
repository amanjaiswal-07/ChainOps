"""
AI-output validation: strict parsing of LLM text into typed models.

The original parsers were fail-open (anything that was not literally
"HIGH" became "LOW"). Here every field must be present with an allowed
value, otherwise OutputParseError is raised and the agent falls back to
its rule baseline with the output flagged as invalid.

`resolve()` then compares a valid LLM answer with the rule baseline:
  * risk levels: the LLM may escalate (LOW -> HIGH) but never downgrade
  * decisions/flags: the deterministic rule wins
Any disagreement is recorded in the output's `meta` and the decision gate
sends the cycle to a human.
"""

import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

from llm_config import LLMResponse

RiskLevel = Literal["LOW", "HIGH"]
_RISK_ORDER = {"LOW": 0, "HIGH": 1}


class OutputParseError(ValueError):
    pass


class DemandOutput(BaseModel):
    demand_risk: RiskLevel
    reasoning: str = Field(min_length=1, max_length=4000)


class RiskOutput(BaseModel):
    supplier_risk: RiskLevel
    logistics_risk: RiskLevel
    reasoning: str = Field(min_length=1, max_length=4000)


class LogisticsOutput(BaseModel):
    expedite: bool
    reasoning: str = Field(min_length=1, max_length=4000)


class CoordinatorOutput(BaseModel):
    decision_type: Literal["REORDER", "HOLD"]
    supplier_id: int | None
    quantity: int = Field(ge=0)
    expedite: bool
    reasoning: str = Field(min_length=1, max_length=8000)

    @model_validator(mode="after")
    def _consistent(self):
        if self.decision_type == "REORDER" and (self.supplier_id is None or self.quantity <= 0):
            raise ValueError("REORDER needs a supplier_id and a positive quantity")
        if self.decision_type == "HOLD" and self.quantity != 0:
            raise ValueError("HOLD must have quantity 0")
        return self


# ---------------------------------------------------------------------------
# Field extraction
# ---------------------------------------------------------------------------

def _field(text: str, key: str, allowed: str) -> str:
    """
    Find `KEY: value` on its own line (tolerating markdown bullets/bold) and
    return the value if it matches `allowed`. Two different values for the
    same key count as malformed.
    """
    # Only look above REASONING, so prose that restates a field cannot clash.
    head = re.split(r"\**REASONING\**\s*:", text or "", maxsplit=1, flags=re.IGNORECASE)[0]
    line_re = re.compile(rf"^[\s>*#\-]*\**{key}\**\s*[:=]\s*\**\s*(.*)$", re.IGNORECASE | re.MULTILINE)
    lines = line_re.findall(head)
    if not lines:
        raise OutputParseError(f"missing field {key}")
    values = set()
    for raw in lines:
        match = re.match(rf"({allowed})\b", raw.strip().strip("*[]"), re.IGNORECASE)
        if not match:
            raise OutputParseError(f"invalid value for {key}: {raw.strip()[:60]!r}")
        values.add(match.group(1).upper())
    if len(values) > 1:
        raise OutputParseError(f"conflicting values for {key}: {sorted(values)}")
    return values.pop()


def _reasoning(text: str) -> str:
    parts = re.split(r"\**REASONING\**\s*:", text or "", maxsplit=1, flags=re.IGNORECASE)
    if len(parts) < 2 or not parts[1].strip():
        raise OutputParseError("missing REASONING")
    return parts[1].strip()


def _model(cls, **data):
    try:
        return cls(**data)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise OutputParseError(f"{'.'.join(map(str, first['loc'])) or cls.__name__}: {first['msg']}") from exc


def parse_demand(text: str) -> DemandOutput:
    return _model(DemandOutput, demand_risk=_field(text, "DEMAND_RISK", "LOW|HIGH"), reasoning=_reasoning(text))


def parse_risk(text: str) -> RiskOutput:
    return _model(RiskOutput,
                  supplier_risk=_field(text, "SUPPLIER_RISK", "LOW|HIGH"),
                  logistics_risk=_field(text, "LOGISTICS_RISK", "LOW|HIGH"),
                  reasoning=_reasoning(text))


def parse_logistics(text: str) -> LogisticsOutput:
    return _model(LogisticsOutput, expedite=_field(text, "EXPEDITE", "TRUE|FALSE") == "TRUE",
                  reasoning=_reasoning(text))


def parse_coordinator(text: str) -> CoordinatorOutput:
    decision_type = _field(text, "DECISION_TYPE", "REORDER|HOLD")
    supplier = _field(text, "SUPPLIER_ID", r"\d+|N/?A|NONE")
    quantity = _field(text, "QUANTITY", r"\d+")
    return _model(CoordinatorOutput,
                  decision_type=decision_type,
                  supplier_id=int(supplier) if supplier.isdigit() else None,
                  quantity=int(quantity),
                  expedite=_field(text, "EXPEDITE", "TRUE|FALSE") == "TRUE",
                  reasoning=_reasoning(text))


# ---------------------------------------------------------------------------
# Combining an LLM answer with the rule baseline
# ---------------------------------------------------------------------------

def resolve(response: LLMResponse, parser, baseline: dict, risk_fields=(), rule_fields=()) -> dict:
    """
    Turn an LLM response into a validated agent output.

    Returns the merged fields plus a `meta` dict:
      source          llm | offline | override
      output_valid    False if the call failed or the text was malformed
      fallback_used   True if the rule baseline replaced the LLM answer
      issues          human-readable problems found
      disagreements   {field: {"llm": x, "rule": y}} for valid but different answers
      rule_baseline   the deterministic answer, for the audit trail
    """
    meta = {"source": response.source, "output_valid": True, "fallback_used": False,
            "issues": [], "disagreements": {},
            "rule_baseline": {k: v for k, v in baseline.items() if k != "reasoning"}}

    if response.error:
        meta.update(output_valid=False, fallback_used=True)
        meta["issues"].append(f"LLM call failed: {response.error}")
        return {**baseline, "meta": meta}

    try:
        parsed = parser(response.text).model_dump()
    except OutputParseError as exc:
        meta.update(output_valid=False, fallback_used=True)
        meta["issues"].append(f"malformed LLM output: {exc}")
        meta["raw_excerpt"] = (response.text or "")[:300]
        return {**baseline, "meta": meta}

    result = dict(parsed)
    for field in risk_fields:
        llm_value, rule_value = parsed[field], baseline[field]
        if llm_value != rule_value:
            meta["disagreements"][field] = {"llm": llm_value, "rule": rule_value}
            # Escalate-only: keep whichever is more severe.
            result[field] = max(llm_value, rule_value, key=_RISK_ORDER.get)
    for field in rule_fields:
        if parsed[field] != baseline[field]:
            meta["disagreements"][field] = {"llm": parsed[field], "rule": baseline[field]}
            result[field] = baseline[field]
    return {**result, "meta": meta}
