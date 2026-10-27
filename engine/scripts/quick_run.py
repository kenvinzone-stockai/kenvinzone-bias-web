"""
Minimal pipeline: fetch yfinance + FRED only, then run bias engine.
Bypasses CFTC (API blocked) and CBOE for speed.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import pandas as pd
from datetime import UTC, date, datetime, timedelta
from core.database import init_db, get_session
from ingestion.raw_storage import store_raw_record

init_db()
print("DB initialized")

start = date.today() - timedelta(days=365 * 3)
end = date.today()

# ── Step 1: yfinance ──────────────────────────────────────────────────────────
print("\n[1/3] Fetching yfinance data...")
from plugins.data.yfinance_plugin import YFinancePlugin
r = YFinancePlugin().run(start, end)
print(f"  -> {r.record_count} records, {len(r.errors)} errors")

def store(records_df, source_tag):
    if records_df.empty:
        return 0
    count = 0
    with get_session() as session:
        for _, row in records_df.iterrows():
            try:
                dt = pd.Timestamp(row["date"]).to_pydatetime()
                val = float(row["value"]) if pd.notna(row.get("value")) else None
                store_raw_record(
                    session,
                    indicator=str(row["indicator"]),
                    observation_date=dt,
                    value=val,
                    source=str(row.get("source", source_tag)),
                    plugin=source_tag,
                    unit=str(row.get("unit", "")),
                    frequency=str(row.get("frequency", "") or ""),
                    # Database timestamps are stored as naive UTC for compatibility.
                    api_response_ts=datetime.now(UTC).replace(tzinfo=None),
                )
                count += 1
            except Exception as e:
                pass
    return count

n = store(r.records, "yfinance")
print(f"  -> Stored {n} records to DB")

# ── Step 2: FRED ──────────────────────────────────────────────────────────────
print("\n[2/3] Fetching FRED data...")
from plugins.data.fred import FREDPlugin
r2 = FREDPlugin().run(start, end)
print(f"  -> {r2.record_count} records, {len(r2.errors)} errors")
if r2.errors:
    for e in r2.errors[:3]:
        print(f"     ERR: {e}")
n2 = store(r2.records, "fred")
print(f"  -> Stored {n2} records to DB")

# ── Step 3: Bias Engine ───────────────────────────────────────────────────────
print("\n[3/3] Running bias engine...")
from bias.engine import BiasEngine

def cb(msg):
    print(" ", msg.encode("ascii", errors="replace").decode("ascii"))

engine = BiasEngine()
results = engine.run(timeframe="weekly", status_callback=cb)

print()
print("=" * 55)
print("BIAS RESULTS")
print("=" * 55)
for asset, result in results.items():
    score  = result.total_score
    regime = result.regime_result.regime.value
    cov    = result.data_coverage
    emoji  = result.regime_result.emoji
    print(f"  {asset:8s} | score={score:+6.1f} | {regime:20s} | coverage={cov:.0%}")

print()
print("Done! Open http://localhost:8501 and click Refresh Data.")
