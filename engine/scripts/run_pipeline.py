"""Full ingestion + bias engine run script."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from core.database import init_db
init_db()

from ingestion.pipeline import run_ingestion
from bias.engine import BiasEngine
from bias.predictive import PredictiveBiasEngine

print("=" * 50)
print("STEP 1: DATA INGESTION")
print("=" * 50)

def cb(msg):
    safe = msg.encode("ascii", errors="replace").decode("ascii")
    print(safe)

summary = run_ingestion(timeframe="weekly", force=True, status_callback=cb)

print()
print("=== INGESTION SUMMARY ===")
print(f"Total records stored: {summary['total_records']}")
for plugin, info in summary.get("plugins", {}).items():
    status = info.get("status", "?")
    stored = info.get("records_stored", 0)
    errors = info.get("errors", [])
    err_str = f" ERRORS: {'; '.join(str(e) for e in errors[:2])}" if errors else ""
    print(f"  [{status:8s}] {plugin}: {stored} records{err_str}")

print()
print("=" * 50)
print("STEP 2: BIAS ENGINE")
print("=" * 50)

engine = BiasEngine()
results = engine.run(timeframe="weekly", status_callback=cb)

print()
print("=== BIAS RESULTS ===")
for asset, result in results.items():
    regime = result.regime_result.regime.value
    score = result.total_score
    cov = result.data_coverage
    print(f"  {asset:8s}: score={score:+.1f}  regime={regime:20s}  coverage={cov:.0%}")

print()
print("=" * 50)
print("STEP 3: UNIFIED 4-WEEK PREDICTIVE MODEL")
print("=" * 50)
predictive = PredictiveBiasEngine().run(force=False, status_callback=cb)
for asset, result in predictive.items():
    print(
        f"  {asset:8s}: {result.status:11s} expected={result.predicted_return:+.2%}  "
        f"P(up)={result.probability_up:.1%}"
    )

print()
print("DONE — Open http://localhost:8501 to see the dashboard")
