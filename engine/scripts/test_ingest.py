"""Quick ingestion test script."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import init_db
init_db()
print("DB initialized")

from ingestion.pipeline import run_ingestion

def cb(msg):
    # Strip emoji for Windows console compatibility
    safe = msg.encode("ascii", errors="replace").decode("ascii")
    print(safe)

print("Starting ingestion (this takes 2-3 minutes)...")
summary = run_ingestion(timeframe="weekly", force=True, status_callback=cb)

print()
print("=== INGESTION SUMMARY ===")
print(f"Total records stored: {summary['total_records']}")
for plugin, info in summary.get("plugins", {}).items():
    status = info.get("status", "?")
    stored = info.get("records_stored", 0)
    errors = info.get("errors", [])
    err_str = f" | ERRORS: {errors[:2]}" if errors else ""
    print(f"  [{status:8s}] {plugin}: {stored} records{err_str}")
