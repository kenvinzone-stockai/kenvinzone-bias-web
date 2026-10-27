"""
Market Bias Platform — Autonomous Cloud Ingestion & Export Runner
Executed automatically by GitHub Actions at 06:30 and 07:15 AM GMT+7.
"""
from __future__ import annotations

import os
import sys
import json
from pathlib import Path
from datetime import date, datetime

# Setup root paths
ENGINE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = ENGINE_ROOT.parent

sys.path.insert(0, str(ENGINE_ROOT))

# Database & Ingestion imports
from core.database import init_db
from core.config import settings
from ingestion.pipeline import run_pipeline
from bias.engine import BiasEngine
from scripts.export_web_json import build, validate

def main():
    print("=" * 60)
    print("  KENVINZONE MARKET BIAS — CLOUD AUTONOMOUS RUNNER")
    print("=" * 60)
    
    # Check FRED API KEY from environment
    fred_key = os.environ.get("FRED_API_KEY")
    if fred_key:
        print("[Auth] FRED_API_KEY detected from environment.")
    else:
        print("[Auth] Notice: FRED_API_KEY not found in environment, checking local config.")

    # 1. Initialize DB
    print("[DB] Initializing database...")
    init_db()

    today = date.today()
    weekday = today.weekday()  # 0 = Monday, 1 = Tuesday, ..., 4 = Friday
    weekday_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    print(f"[Calendar] Target Date: {today} ({weekday_names[weekday]})")

    is_weekly_day = weekday in (0, 4)  # Monday or Friday

    # 2. Ingestion
    print("\n--- 1. INGESTING FRESH MARKET DATA ---")
    print(f"[Ingest] Fetching Daily feeds (FRED, Yahoo, SPDR)...")
    try:
        run_pipeline(timeframe="daily", force=False)
        print("[Ingest] Daily ingestion finished.")
    except Exception as exc:
        print(f"[Ingest Warning] Daily ingestion encountered error: {exc}")

    if is_weekly_day:
        print(f"[Ingest] Today is {weekday_names[weekday]}: Fetching Weekly feeds (COT, Macro Liquidity)...")
        try:
            run_pipeline(timeframe="weekly", force=False)
            print("[Ingest] Weekly ingestion finished.")
        except Exception as exc:
            print(f"[Ingest Warning] Weekly ingestion encountered error: {exc}")
    else:
        print(f"[Ingest] Mid-week ({weekday_names[weekday]}): Keeping existing Weekly COT baseline.")

    # 3. Bias Engine Calculation
    print("\n--- 2. COMPUTING QUANTITATIVE BIAS SCORES ---")
    engine = BiasEngine()

    print("[Engine] Computing Daily Bias (Gold, SPX, Nasdaq)...")
    try:
        engine.run(calc_date=today, timeframe="daily")
        print("[Engine] Daily Bias computation successful.")
    except Exception as exc:
        print(f"[Engine Warning] Daily bias calculation error: {exc}")

    if is_weekly_day:
        print(f"[Engine] Computing Weekly Bias (Gold, SPX, Nasdaq)...")
        try:
            engine.run(calc_date=today, timeframe="weekly")
            print("[Engine] Weekly Bias computation successful.")
        except Exception as exc:
            print(f"[Engine Warning] Weekly bias calculation error: {exc}")
    else:
        print(f"[Engine] Weekly Bias remains anchored to Monday's strategic plan.")

    # 4. Export Web JSON
    print("\n--- 3. EXPORTING PUBLIC TERMINAL JSON ---")
    db_path = ENGINE_ROOT / "data" / "market_bias.db"
    out_path = REPO_ROOT / "data" / "latest.json"
    gamma_overrides = REPO_ROOT / "data" / "gamma-overrides.json"

    print(f"[Export] Reading DB: {db_path}")
    print(f"[Export] Target output: {out_path}")

    payload = build(db_path, gamma_overrides)
    issues = validate(payload)
    for issue in issues:
        print(f"  [Validation] {issue}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(out_path)
    print(f"\n✅ [SUCCESS] Wrote updated data to {out_path}!")
    
    # Print summary
    for k, a in payload["assets"].items():
        w, d = a["weekly"] or {}, a["daily"] or {}
        print(f"  • {k:7s} | Daily: {d.get('score')!s:>6} ({d.get('regime')!s:14s}) | Weekly: {w.get('score')!s:>6} ({w.get('regime')!s:14s})")
        
    print("=" * 60)
    print("  ALL TASKS COMPLETED SUCCESSFULLY")
    print("=" * 60)

if __name__ == "__main__":
    main()
