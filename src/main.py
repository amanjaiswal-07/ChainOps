"""
Supply Chain Control Tower - CLI: one recorded decision cycle per product.

Run from the repo root:  python -m src.main
"""

import os
import sys
from datetime import datetime
import time
import asyncio

if __name__ == '__main__':
    current_dir = os.path.dirname(os.path.abspath(__file__))
    if current_dir not in sys.path:
        sys.path.insert(0, current_dir)

from db_init import ensure_database
from llm_config import LLMConfigError, check_configuration, resolve_mode
from workflow import arun_cycle


def print_section(title):
    """Print formatted section header."""
    print("\n" + "="*70)
    print(f"  {title}")
    print("="*70)


def print_streaming_dots(message, duration=1.5):
    """Print message with animated dots."""
    print(f"{message}", end='', flush=True)
    for _ in range(3):
        time.sleep(duration / 3)
        print(".", end='', flush=True)
    print(" done")


async def run_all_products_async(product_ids):
    """
    Run one recorded decision cycle per product.

    The agents call the LLM synchronously, so the cycles effectively run
    one after another. Each is stored as a decision record (governance.py).
    """
    print_section("Processing All Products")
    tasks = [arun_cycle(pid) for pid in product_ids]
    return await asyncio.gather(*tasks)


def print_product_summary(result):
    """Print summary for one product."""
    if not result:
        print("\nNo result available")
        return

    snapshot = result.get('snapshot') or {}
    final_decision = result.get('final_decision') or {}

    product = snapshot.get('product', {})
    product_name = product.get('name', f"Product {result.get('product_id')}")

    print(f"\n{product_name}  [{result['decision_id']}]")
    print(f"   Decision: {final_decision.get('decision_type', 'N/A')}")
    print(f"   Risk: {result.get('risk_level') or 'N/A'}")
    print(f"   Status: {result['status']}")

    details = final_decision.get('details', {})
    if details.get('supplier_id'):
        print(f"   Supplier: #{details.get('supplier_id')}")
        print(f"   Quantity: {details.get('quantity')} units")
        print(f"   Expedite: {'Yes' if details.get('expedite') else 'No'}")


async def run_supply_chain_cycle_async():
    """Run a decision cycle for all products."""

    print_section("SUPPLY CHAIN CONTROL TOWER")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print(f"LLM mode: {resolve_mode()}")

    # Initialize database
    print_section("Step 1: Database Initialization")
    try:
        print_streaming_dots("Initializing database", 1.0)
        ensure_database()
        print("Database ready")
    except Exception as e:
        print(f"Database initialization failed: {e}")
        return

    # Process all products
    product_ids = [1, 2, 3]

    try:
        results = await run_all_products_async(product_ids)

        # Display summaries
        print_section("Results Summary")
        for result in results:
            print_product_summary(result)
        print("\nDecisions in PENDING_APPROVAL wait for a human: use the API or the Streamlit UI.")

    except Exception as e:
        print(f"Workflow failed: {type(e).__name__}: {e}")


def main():
    """Main entry point."""
    try:
        check_configuration()
    except LLMConfigError as e:
        print(f"ERROR: {e}")
        return

    print_section("Observability Check")
    from llm_config import verify_tracing
    verify_tracing()

    asyncio.run(run_supply_chain_cycle_async())


if __name__ == '__main__':
    main()
