"""
Central configuration for ChainOps.

Every business threshold the system uses lives here so that it is visible,
documented and overridable through environment variables (see .env.example).
Nothing in this file is a secret; API keys are read in llm_config.py only.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Repository root (one level above src/). Used to build paths that do not
# depend on the directory the process was started from.
PROJECT_ROOT = Path(__file__).resolve().parents[1]

load_dotenv(PROJECT_ROOT / ".env")


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "supply_chain.db"
DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite:///{DEFAULT_DB_PATH.as_posix()}"

# ---------------------------------------------------------------------------
# Agent classification rules (these mirror the rules written in the prompts)
# ---------------------------------------------------------------------------
# Risk agent: a supplier below this reliability makes supplier risk HIGH.
SUPPLIER_RELIABILITY_THRESHOLD = _float("SUPPLIER_RELIABILITY_THRESHOLD", 0.90)
# Risk agent: a shipment arriving later than this makes logistics risk HIGH.
LOGISTICS_MAX_ETA_DAYS = _int("LOGISTICS_MAX_ETA_DAYS", 7)
# Logistics agent: "near the reorder point" means stock <= ROP * this factor.
NEAR_REORDER_FACTOR = _float("NEAR_REORDER_FACTOR", 1.2)

# ---------------------------------------------------------------------------
# Data validation
# ---------------------------------------------------------------------------
# A pending/confirmed PO older than this with no in-transit shipment is stale.
STALE_PO_DAYS = _int("STALE_PO_DAYS", 30)
# Events older than this are rejected: acting on old news is unsafe.
EVENT_MAX_AGE_HOURS = _int("EVENT_MAX_AGE_HOURS", 24)
# Allowed clock skew for event timestamps that are slightly in the future.
EVENT_FUTURE_SKEW_MINUTES = _int("EVENT_FUTURE_SKEW_MINUTES", 5)

# ---------------------------------------------------------------------------
# Event trigger thresholds (when does an event start a decision cycle?)
# ---------------------------------------------------------------------------
DEMAND_SPIKE_THRESHOLD = _float("DEMAND_SPIKE_THRESHOLD", 1.25)
SHIPMENT_DELAY_THRESHOLD_DAYS = _int("SHIPMENT_DELAY_THRESHOLD_DAYS", 2)

# ---------------------------------------------------------------------------
# Governance policy
# ---------------------------------------------------------------------------
# Hard ceiling: an order above this is never placed as-is.
MAX_ORDER_QUANTITY = _int("MAX_ORDER_QUANTITY", 1000)
# Orders above this quantity always need a human, whatever the agents say.
APPROVAL_QUANTITY_THRESHOLD = _int("APPROVAL_QUANTITY_THRESHOLD", 300)

# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------
# auto    -> live if OPENROUTER_API_KEY is set, otherwise offline
# live    -> always call the LLM; fail with a clear error if no key
# offline -> never call the LLM; agents use their deterministic rule baseline
LLM_MODE = os.getenv("LLM_MODE", "auto").lower()
LLM_TIMEOUT_SECONDS = _float("LLM_TIMEOUT_SECONDS", 30)
LLM_MAX_RETRIES = _int("LLM_MAX_RETRIES", 2)

# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
MAX_REQUEST_BYTES = _int("MAX_REQUEST_BYTES", 16_384)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
