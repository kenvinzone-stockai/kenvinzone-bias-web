"""
Export public Market Bias data for bias.kenvinzone.com (Schema v1.0).

Reads the MBP SQLite database in READ-ONLY mode and writes a single JSON
payload that the static web terminal fetches at runtime.

Rules (see kenvinzone-bias-web/CLAUDE.md):
  * The engine is the single source of truth: score, regime and thresholds
    are copied verbatim, never recomputed here or in the frontend.
  * Only public fields are exported. Never put VIP data in this file:
    everything deployed to a static host is downloadable.
  * Missing data is exported as null, never as an invented number.

Usage (from market-bias-platform/):
    python scripts/export_web_json.py
    python scripts/export_web_json.py --db data/market_bias.db \
        --out ../kenvinzone-bias-web/data/latest.json \
        --gamma-overrides ../kenvinzone-bias-web/data/gamma-overrides.json

Stdlib only (no pandas) so it runs from any Python 3.9+.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA_VERSION = "1.0"
VN_TZ = timezone(timedelta(hours=7))

ROOT = Path(__file__).resolve().parent.parent          # market-bias-platform/
DEFAULT_DB = ROOT / "data" / "market_bias.db"
WEB_ROOT = ROOT.parent / "kenvinzone-bias-web"
DEFAULT_OUT = WEB_ROOT / "data" / "latest.json"
DEFAULT_OVERRIDES = WEB_ROOT / "data" / "gamma-overrides.json"

# Engine asset key -> public display + options underlying (options_data/service.py)
ASSETS = {
    "GOLD":   {"label": "Gold (XAUUSD)", "underlying": "GLD", "spot_symbol": "XAUUSD", "spot_indicator": "gold_futures", "spot_unit": "USD/oz"},
    "SPX":    {"label": "S&P 500",       "underlying": "SPY", "spot_symbol": "SPX",    "spot_indicator": "spx_close",    "spot_unit": "pts"},
    "NASDAQ": {"label": "Nasdaq 100",    "underlying": "QQQ", "spot_symbol": "NDX",    "spot_indicator": "ndx_close",    "spot_unit": "pts"},
}
TIMEFRAMES = ("weekly", "daily")

# Fallback only; the active framework's thresholds are read from the DB.
DEFAULT_THRESHOLDS = {
    "strong_bullish_min": 15.0, "bullish_min": 7.0,
    "bearish_max": -7.0, "strong_bearish_max": -15.0,
}

# Staleness budget shown by the frontend (hours).
STALE_AFTER_HOURS = {"daily": 36, "weekly": 8 * 24, "gamma": 36}


# ── helpers ──────────────────────────────────────────────────────────────────
def num(v, nd=2):
    """Round finite numbers; map None/NaN/inf to None."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return round(f, nd)


def iso_date(v) -> str | None:
    if v is None:
        return None
    return str(v)[:10]


def loads(v, default):
    if not v:
        return default
    try:
        return json.loads(v)
    except (TypeError, ValueError):
        return default


def connect_ro(db: Path) -> sqlite3.Connection:
    """Open read-only. If the live WAL database can't be opened in place
    (locked by Streamlit/scheduler, network/virtual drive), read from a
    temporary snapshot copy instead. The original DB is never written."""
    if not db.exists():
        sys.exit(f"[export] DB not found: {db}")
    try:
        conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()
    except sqlite3.OperationalError as exc:
        import shutil, tempfile
        snap = Path(tempfile.mkdtemp(prefix="mbp_export_")) / db.name
        shutil.copy2(db, snap)
        wal = db.with_name(db.name + "-wal")
        if wal.exists():
            shutil.copy2(wal, snap.with_name(snap.name + "-wal"))
        print(f"[export] live DB not readable in place ({exc}); using snapshot {snap}")
        conn = sqlite3.connect(snap.as_posix())
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn, name) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


# ── readers ──────────────────────────────────────────────────────────────────
def read_thresholds(conn) -> tuple[dict, int | None]:
    if not table_exists(conn, "framework_versions"):
        return DEFAULT_THRESHOLDS, None
    cols = [r[1] for r in conn.execute("PRAGMA table_info(framework_versions)")]
    order = "id DESC"
    where = ""
    if "is_active" in cols:
        where = "WHERE is_active = 1"
    row = conn.execute(
        f"SELECT * FROM framework_versions {where} ORDER BY {order} LIMIT 1"
    ).fetchone()
    if row is None:
        return DEFAULT_THRESHOLDS, None
    th = loads(row["regime_thresholds"], None) if "regime_thresholds" in cols else None
    version = row["version"] if "version" in cols else row["id"]
    return (th or DEFAULT_THRESHOLDS), version


def read_bias(conn, asset: str, timeframe: str) -> dict | None:
    row = conn.execute(
        """SELECT date, total_score, regime, prev_score, score_change, prev_regime,
                  category_scores, top_positive, top_negative, data_coverage,
                  framework_version, created_at
           FROM bias_results
           WHERE asset = ? AND timeframe = ?
           ORDER BY date DESC, id DESC LIMIT 1""",
        (asset, timeframe),
    ).fetchone()
    if row is None:
        return None

    cats = loads(row["category_scores"], {})
    categories = sorted(
        (
            {
                "key": k,
                "weight": num(v.get("weight"), 4),
                "rawScore": num(v.get("raw_score"), 1),
                "contribution": num(v.get("contribution"), 2),
            }
            for k, v in cats.items() if isinstance(v, dict)
        ),
        key=lambda c: abs(c["contribution"] or 0),
        reverse=True,
    )

    def drivers(raw):
        return [
            {"name": d.get("name"), "contribution": num(d.get("contribution"), 2)}
            for d in loads(raw, [])[:5] if isinstance(d, dict)
        ]

    return {
        "asOf": iso_date(row["date"]),
        "computedAt": str(row["created_at"]) if row["created_at"] else None,
        "score": num(row["total_score"], 1),
        "regime": row["regime"],
        "prevScore": num(row["prev_score"], 1),
        "scoreChange": num(row["score_change"], 1),
        "prevRegime": row["prev_regime"],
        "dataCoverage": num(row["data_coverage"], 3),
        "frameworkVersion": row["framework_version"],
        "categories": categories,
        "topPositive": drivers(row["top_positive"]),
        "topNegative": drivers(row["top_negative"]),
    }


def read_gamma_db(conn, underlying: str) -> dict | None:
    if not table_exists(conn, "option_daily_summaries"):
        return None
    # Aggregate view = nearest expiration of the latest snapshot.
    row = conn.execute(
        """SELECT * FROM option_daily_summaries
           WHERE symbol = ?
             AND snapshot_date = (SELECT MAX(snapshot_date)
                                  FROM option_daily_summaries WHERE symbol = ?)
           ORDER BY days_to_expiration ASC LIMIT 1""",
        (underlying, underlying),
    ).fetchone()
    if row is None:
        return None
    return {
        "source": "mbp_engine",
        "asOf": iso_date(row["snapshot_date"]),
        "expiration": iso_date(row["expiration"]),
        "spot": num(row["spot_price"]),
        "putWall": num(row["put_wall"]),
        "callWall": num(row["call_wall"]),
        "gammaFlip": num(row["gamma_flip"]),
        "maxPain": num(row["max_pain"]),
        "netGex": num(row["net_gex"], 0),
        "expectedMove": num(row["expected_move"]),
        "putCallOiRatio": num(row["put_call_oi_ratio"], 3),
    }


def read_gamma_overrides(path: Path) -> dict:
    """Manual levels typed by the Founder (e.g. from the weekly slide deck)."""
    if not path or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        print(f"[export] WARNING invalid overrides file {path}: {exc}")
        return {}
    return {k: v for k, v in data.items() if not k.startswith("_")}


def read_spot_price(conn, indicator: str) -> float | None:
    if not table_exists(conn, "raw_data"):
        return None
    row = conn.execute(
        """SELECT value FROM raw_data
           WHERE indicator = ? AND value IS NOT NULL
           ORDER BY date DESC, id DESC LIMIT 1""",
        (indicator,),
    ).fetchone()
    if row and row["value"] is not None:
        try:
            return float(row["value"])
        except (ValueError, TypeError):
            pass
    return None


def finalize_gamma(g: dict | None, underlying: str, spot_meta: dict | None = None, conn=None) -> dict:
    empty = {
        "underlying": underlying, "source": None, "asOf": None, "spot": None,
        "putWall": None, "callWall": None, "gammaFlip": None,
        "netGex": None, "gammaRegime": None, "spotAsset": None,
    }
    if not g:
        return empty
    out = {**empty, **{k: g.get(k) for k in g}}
    out["underlying"] = underlying
    for k in ("spot", "putWall", "callWall", "gammaFlip", "maxPain", "expectedMove"):
        if k in out:
            out[k] = num(out[k])
    out["netGex"] = num(out.get("netGex"), 0)
    spot, flip = out.get("spot"), out.get("gammaFlip")
    if spot is not None and flip is not None:
        out["gammaRegime"] = "positive" if spot >= flip else "negative"
    elif out.get("netGex") is not None:
        out["gammaRegime"] = "positive" if out["netGex"] >= 0 else "negative"

    # Spot asset conversion (e.g. GLD -> XAUUSD, SPY -> SPX, QQQ -> NDX)
    if g.get("spotAsset"):
        out["spotAsset"] = g["spotAsset"]
    elif spot_meta and conn:
        spot_val = num(g.get("spot_price")) or read_spot_price(conn, spot_meta.get("spot_indicator"))
        etf_spot = out.get("spot")
        if spot_val and etf_spot and etf_spot > 0:
            ratio = spot_val / etf_spot
            out["spotAsset"] = {
                "symbol": spot_meta.get("spot_symbol"),
                "spot": num(spot_val, 2),
                "ratio": num(ratio, 4),
                "unit": spot_meta.get("spot_unit", ""),
                "putWall": num(out["putWall"] * ratio, 1) if out.get("putWall") is not None else None,
                "callWall": num(out["callWall"] * ratio, 1) if out.get("callWall") is not None else None,
                "gammaFlip": num(out["gammaFlip"] * ratio, 1) if out.get("gammaFlip") is not None else None,
            }
    return out


def divergence(weekly: dict | None, daily: dict | None) -> dict:
    """Same-sign rule on engine scores; NEUTRAL band uses engine thresholds."""
    if not weekly or not daily or weekly["score"] is None or daily["score"] is None:
        return {"status": "UNKNOWN"}
    w, d = weekly["score"], daily["score"]
    if (w > 0 > d) or (w < 0 < d):
        status = "DIVERGENCE"
    else:
        status = "ALIGNED"
    return {"status": status, "weeklyScore": w, "dailyScore": d,
            "rule": "DIVERGENCE when weekly and daily scores have opposite signs"}


# ── main ─────────────────────────────────────────────────────────────────────
def build(db: Path, overrides_path: Path) -> dict:
    conn = connect_ro(db)
    try:
        thresholds, fw_version = read_thresholds(conn)
        overrides = read_gamma_overrides(overrides_path)
        assets = {}
        for key, meta in ASSETS.items():
            tf = {t: read_bias(conn, key, t) for t in TIMEFRAMES}
            g = read_gamma_db(conn, meta["underlying"]) or None
            if key in overrides:                       # manual wins if provided
                g = {"source": "manual", **overrides[key]}
            assets[key] = {
                "label": meta["label"],
                "weekly": tf["weekly"],
                "daily": tf["daily"],
                "divergence": divergence(tf["weekly"], tf["daily"]),
                "gamma": finalize_gamma(g, meta["underlying"], spot_meta=meta, conn=conn),
            }
    finally:
        conn.close()

    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(VN_TZ).isoformat(timespec="seconds"),
        "frameworkVersion": fw_version,
        "scale": {"min": -100, "max": 100},
        "regimeThresholds": {
            "strongBullishMin": num(thresholds.get("strong_bullish_min"), 1),
            "bullishMin": num(thresholds.get("bullish_min"), 1),
            "bearishMax": num(thresholds.get("bearish_max"), 1),
            "strongBearishMax": num(thresholds.get("strong_bearish_max"), 1),
        },
        "staleAfterHours": STALE_AFTER_HOURS,
        "disclaimer": {
            "vi": "Dữ liệu định lượng phục vụ mục đích giáo dục, không phải khuyến nghị đầu tư.",
            "en": "Educational quantitative data. Not investment advice.",
        },
        "assets": assets,
    }


def validate(payload: dict) -> list[str]:
    errs = []
    lo, hi = payload["scale"]["min"], payload["scale"]["max"]
    for k, a in payload["assets"].items():
        for tf in TIMEFRAMES:
            b = a.get(tf)
            if b is None:
                errs.append(f"{k}.{tf}: no bias_results row (warning)")
                continue
            s = b["score"]
            if s is not None and not (lo <= s <= hi):
                errs.append(f"{k}.{tf}: score {s} outside [{lo},{hi}] (ERROR)")
        g = a["gamma"]
        if g["putWall"] is not None and g["callWall"] is not None and g["putWall"] >= g["callWall"]:
            errs.append(f"{k}.gamma: putWall >= callWall (ERROR)")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--gamma-overrides", type=Path, default=DEFAULT_OVERRIDES)
    args = ap.parse_args()

    payload = build(args.db, args.gamma_overrides)
    issues = validate(payload)
    for i in issues:
        print(f"[export] {i}")
    if any("(ERROR)" in i for i in issues):
        print("[export] aborted: fix errors above, nothing written")
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(args.out)                                # atomic swap
    print(f"[export] wrote {args.out}")
    for k, a in payload["assets"].items():
        w, d = a["weekly"] or {}, a["daily"] or {}
        print(f"  {k:7s} weekly {w.get('score')!s:>6} {w.get('regime')!s:15s} "
              f"daily {d.get('score')!s:>6} {d.get('regime')!s:15s} gamma={a['gamma']['source']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
