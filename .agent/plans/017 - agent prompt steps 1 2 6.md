# Agent Task: Pre-Paper-Trading Validation — Steps 1, 2 and 6

**Branch:** b3-backtest  
**Date:** 2026-05-15  
**Context:** The v7 grid search is complete with Conclusion B confirmed: VRP exists in BOVA11
and PETR4 at mid-price execution. Three pre-paper-trading checks are required before
deploying capital. This task covers all three.

**Important:** Run steps in order. Step 1 is a hard gate — if it returns FAIL,
STOP and report before running Steps 2 and 6.

---

## Step 1 — B3 Official Bulletin Validation

### Why

rb3's `bid` and `ask` columns have never been validated against any external source.
Every conclusion about mid execution viability depends on those numbers being real
B3-published quotes. The 16Δ deep dive showed spread/mark of 56%/44% (puts/calls) —
unusually wide for a liquid ETF — which raises the question of whether these are
real order book quotes or computed estimates.

B3 publishes free daily bulletins at:
`https://www.b3.com.br/pesquisapregao/download?filelist=PRYYMMDD.zip`

All dates from 2018-2025 confirmed accessible (HTTP 200). The bulletins contain:

- `PR` (negotiation) files: last traded price, avg price, min/max, volume per ticker
- `IN` (product) files: option specs including exercise style (European/American)

### Task

Create `scripts/validate_b3_prices.py` that:

1. For each of the 10 validation dates, downloads both the PR and IN bulletins
2. For each date, queries rb3 DB for the BOVA11 options closest to 16Δ put and call
   at the next monthly expiration
3. Matches rb3 rows to B3 bulletin rows on (type, strike ±1%, expiry ±5 days)
4. Computes validation metrics
5. Writes a report and a pass/fail verdict

#### Validation dates

```python
VALIDATION_DATES = [
    "20180615",   # Normal 2018 trading
    "20190412",   # Normal 2019 trading
    "20200316",   # COVID crash
    "20200915",   # Mid-COVID recovery
    "20210512",   # Post-vaccine normal
    "20220831",   # Pre-election 2022
    "20221031",   # Lula election day
    "20230815",   # Normal 2023
    "20241015",   # Recent control date
    "20250110",   # Recent 2025
]
```

#### B3 bulletin fetcher

The fetcher code already exists at `scripts/b3_bulletin_fetcher.py` (from Plan 008).
If it doesn't exist yet, create it with the following downloader and parser:

```python
# scripts/b3_bulletin_fetcher.py

import requests
import zipfile
import pandas as pd
import xml.etree.ElementTree as ET
from typing import Literal
import os
import shutil
from time import sleep


HEADERS = {
    "referer": (
        "https://www.b3.com.br/pt_br/market-data-e-indices/servicos-de-dados/"
        "market-data/historico/boletins-diarios/pesquisa-por-pregao/"
        "pesquisa-por-pregao/"
    )
}


def _parse_xml(path):
    try:
        return ET.parse(path).getroot()
    except Exception as e:
        print(f"XML parse error: {e}")
        return None


def parse_negotiation_xml(xml_path: str) -> pd.DataFrame:
    root = _parse_xml(xml_path)
    if root is None:
        return pd.DataFrame()
    ns = {
        "bvmf217": "urn:bvmf.217.01.xsd",
        "head": "urn:iso:std:iso:20022:tech:xsd:head.001.001.01",
    }
    rows = []
    for rpt in root.findall(".//bvmf217:PricRpt", ns):
        t = rpt.findtext("bvmf217:SctyId/bvmf217:TckrSymb", namespaces=ns)
        first = rpt.findtext("bvmf217:FinInstrmAttrbts/bvmf217:FrstPric", namespaces=ns)
        if not first:
            continue
        rows.append({
            "ID": rpt.findtext("bvmf217:FinInstrmId/bvmf217:OthrId/bvmf217:Id", namespaces=ns),
            "TradeDate": rpt.findtext("bvmf217:TradDt/bvmf217:Dt", namespaces=ns),
            "Ticker": t,
            "FirstPrice": first,
            "MinPrice": rpt.findtext("bvmf217:FinInstrmAttrbts/bvmf217:MinPric", namespaces=ns),
            "MaxPrice": rpt.findtext("bvmf217:FinInstrmAttrbts/bvmf217:MaxPric", namespaces=ns),
            "LastPrice": rpt.findtext("bvmf217:FinInstrmAttrbts/bvmf217:LastPric", namespaces=ns),
            "AvgPrice": rpt.findtext("bvmf217:FinInstrmAttrbts/bvmf217:TradAvrgPric", namespaces=ns),
            "TradeQty": rpt.findtext("bvmf217:TradDtls/bvmf217:TradQty", namespaces=ns),
        })
    return pd.DataFrame(rows)


def parse_products_xml(xml_path: str) -> pd.DataFrame:
    root = _parse_xml(xml_path)
    if root is None:
        return pd.DataFrame()
    ns = {
        "bvmf100": "urn:bvmf.100.02.xsd",
        "head": "urn:iso:std:iso:20022:tech:xsd:head.001.001.01",
    }
    rows = []
    for inst in root.findall(".//bvmf100:Instrm", ns):
        ticker = inst.findtext(
            "bvmf100:InstrmInf/bvmf100:OptnOnEqtsInf/bvmf100:TckrSymb",
            namespaces=ns,
        )
        if not ticker:
            continue
        rows.append({
            "Ticker": ticker,
            "Ação": inst.findtext("bvmf100:FinInstrmAttrCmon/bvmf100:Asst", namespaces=ns),
            "ID_ação": inst.findtext(
                "bvmf100:InstrmInf/bvmf100:OptnOnEqtsInf"
                "/bvmf100:UndrlygInstrmId/bvmf100:OthrId/bvmf100:Id",
                namespaces=ns,
            ),
            "Style": inst.findtext(
                "bvmf100:InstrmInf/bvmf100:OptnOnEqtsInf/bvmf100:OptnStyle",
                namespaces=ns,
            ),
            "Type": inst.findtext(
                "bvmf100:InstrmInf/bvmf100:OptnOnEqtsInf/bvmf100:OptnTp",
                namespaces=ns,
            ),
            "Strike": inst.findtext(
                "bvmf100:InstrmInf/bvmf100:OptnOnEqtsInf/bvmf100:ExrcPric",
                namespaces=ns,
            ),
            "Maturity": inst.findtext(
                "bvmf100:InstrmInf/bvmf100:OptnOnEqtsInf/bvmf100:XprtnDt",
                namespaces=ns,
            ),
        })
    return pd.DataFrame(rows)


def _download_zip(code: str, save_dir: str) -> str | None:
    url = f"https://www.b3.com.br/pesquisapregao/download?filelist={code}.zip,"
    try:
        r = requests.get(url, headers=HEADERS, timeout=60)
        r.raise_for_status()
        path = os.path.join(save_dir, f"{code}.zip")
        with open(path, "wb") as f:
            f.write(r.content)
        return path
    except Exception as e:
        print(f"  Download failed for {code}: {e}")
        return None


def _extract_zip(zip_path: str, extract_dir: str) -> list[str]:
    files = []
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)
            for name in zf.namelist():
                full = os.path.join(extract_dir, name)
                if name.endswith(".zip"):
                    # nested zip
                    nested_dir = full.replace(".zip", "")
                    os.makedirs(nested_dir, exist_ok=True)
                    files.extend(_extract_zip(full, nested_dir))
                    os.remove(full)
                else:
                    files.append(full)
        os.remove(zip_path)
    except Exception as e:
        print(f"  Extract failed: {e}")
    return files


def get_b3_daily(
    date_str: str,
    bulletin_type: Literal["negotiation", "product"] = "negotiation",
    cache_dir: str = "/tmp/b3_bulletins",
    retries: int = 0,
) -> pd.DataFrame:
    """
    Download and parse one day's B3 bulletin.
    date_str: YYYYMMDD (e.g. '20200316')
    bulletin_type: 'negotiation' (PR, traded prices) or 'product' (IN, contract specs)
    """
    prefix = "PR" if bulletin_type == "negotiation" else "IN"
    code = prefix + date_str[2:]   # e.g. PR200316
    work_dir = os.path.join(cache_dir, code)
    os.makedirs(work_dir, exist_ok=True)

    try:
        zip_path = _download_zip(code, cache_dir)
        if not zip_path:
            return pd.DataFrame()
        xml_files = _extract_zip(zip_path, work_dir)
        xml_file = next((f for f in xml_files if f.endswith(".xml")), None)
        if not xml_file:
            return pd.DataFrame()
        if bulletin_type == "negotiation":
            df = parse_negotiation_xml(xml_file)
        else:
            df = parse_products_xml(xml_file)
        return df
    except zipfile.BadZipFile:
        if retries >= 3:
            return pd.DataFrame()
        sleep(1.0 * (retries + 1))
        return get_b3_daily(date_str, bulletin_type, cache_dir, retries + 1)
    except Exception as e:
        print(f"  Error for {date_str} {bulletin_type}: {e}")
        return pd.DataFrame()
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
```

#### Main validation script

```python
# scripts/validate_b3_prices.py
"""
Validates rb3 database prices against B3 official daily bulletin data.

For 10 dates spanning 2018-2025, downloads B3's authoritative negotiation and
product bulletins and compares against rb3 database values for the nearest
16-delta put and call on BOVA11.

Also extracts the official B3 exercise style for BOVA11 options (European/American).

Outputs:
  output/validation/validation_targets.csv      -- rb3 data for 20 contracts
  output/validation/validation_b3_official.csv  -- B3 official data for same contracts
  output/validation/validation_comparison.csv   -- side-by-side comparison
  docs/YYYY-MM-DD - rb3 price validation.md     -- human-readable report + verdict

Exit code 0 = PASS or PARTIAL (proceed)
Exit code 1 = FAIL (stop, investigate)
"""

import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.b3_bulletin_fetcher import get_b3_daily

# ── Config ─────────────────────────────────────────────────────────────────
DB_PATH = "data/B3/b3_options_rb3.db"
OUTPUT_DIR = Path("output/validation")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

VALIDATION_DATES = [
    "20180615", "20190412", "20200316", "20200915",
    "20210512", "20220831", "20221031", "20230815",
    "20241015", "20250110",
]

# ── Step 1: Query rb3 DB for target contracts ───────────────────────────────

def get_rb3_targets(db_path: str, dates: list[str]) -> pd.DataFrame:
    conn = sqlite3.connect(db_path)
    rows = []
    for date_str in dates:
        date_fmt = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
        for opt_type, target_delta in [("put", -0.16), ("call", 0.16)]:
            q = """
                SELECT date, expiration, type, strike,
                       mark, bid, ask, volume, delta, implied_volatility
                FROM options_data
                WHERE underlying = 'bova11'
                  AND date = ?
                  AND type = ?
                  AND expiration > date(date, '+20 days')
                  AND expiration <= date(date, '+60 days')
                  AND mark > 0
                  AND delta IS NOT NULL
                ORDER BY ABS(delta - ?) ASC
                LIMIT 1
            """
            df = pd.read_sql(q, conn, params=(date_fmt, opt_type, target_delta))
            if not df.empty:
                df["validation_date"] = date_str
                rows.append(df)
    conn.close()
    if not rows:
        return pd.DataFrame()
    result = pd.concat(rows, ignore_index=True)
    result.columns = [
        "rb3_date", "rb3_expiration", "rb3_type", "rb3_strike",
        "rb3_mark", "rb3_bid", "rb3_ask", "rb3_volume",
        "rb3_delta", "rb3_iv", "validation_date",
    ]
    return result


# ── Step 2: Fetch B3 bulletins ──────────────────────────────────────────────

def fetch_all_bulletins(dates: list[str]) -> tuple[dict, dict]:
    """Returns (neg_cache, prod_cache) keyed by date string."""
    neg_cache, prod_cache = {}, {}
    for date_str in dates:
        print(f"  [{date_str}] negotiation...", end=" ", flush=True)
        df = get_b3_daily(date_str, "negotiation")
        neg_cache[date_str] = (
            df[df["Ticker"].str.startswith("BOVA", na=False)].copy()
            if not df.empty else pd.DataFrame()
        )
        print(f"{len(neg_cache[date_str])} BOVA rows")
        time.sleep(0.5)   # be polite to B3

        print(f"  [{date_str}] product...", end=" ", flush=True)
        df = get_b3_daily(date_str, "product")
        prod_cache[date_str] = (
            df[df["Ticker"].str.startswith("BOVA", na=False)].copy()
            if not df.empty else pd.DataFrame()
        )
        print(f"{len(prod_cache[date_str])} BOVA rows")
        time.sleep(0.5)
    return neg_cache, prod_cache


# ── Step 3: Match B3 rows to rb3 targets ───────────────────────────────────

def match_contracts(
    targets: pd.DataFrame,
    neg_cache: dict,
    prod_cache: dict,
) -> pd.DataFrame:
    rows = []
    for _, t in targets.iterrows():
        date_str = t["validation_date"]
        prod = prod_cache.get(date_str, pd.DataFrame())
        neg  = neg_cache.get(date_str, pd.DataFrame())

        b3_ticker = b3_style = b3_last = b3_avg = b3_min = b3_max = b3_qty = None
        b3_found = False

        if not prod.empty and not neg.empty:
            type_map = {"call": "CALL", "put": "PUT"}
            b3_type = type_map.get(t["rb3_type"], t["rb3_type"].upper())
            try:
                prod["Strike_f"] = prod["Strike"].astype(float)
                prod["Mat_d"]    = pd.to_datetime(prod["Maturity"])
                t_strike = float(t["rb3_strike"])
                t_exp    = pd.to_datetime(t["rb3_expiration"])

                mask = (
                    (prod["Type"] == b3_type)
                    & prod["Strike_f"].between(t_strike * 0.99, t_strike * 1.01)
                    & prod["Mat_d"].between(
                        t_exp - pd.Timedelta(days=5),
                        t_exp + pd.Timedelta(days=5),
                    )
                )
                matched = prod[mask]
                if not matched.empty:
                    b3_ticker = matched.iloc[0]["Ticker"]
                    b3_style  = matched.iloc[0].get("Style", "UNKNOWN")
                    neg_row   = neg[neg["Ticker"] == b3_ticker]
                    if not neg_row.empty:
                        r = neg_row.iloc[0]
                        b3_last = float(r["LastPrice"]) if r["LastPrice"] else None
                        b3_avg  = float(r["AvgPrice"])  if r["AvgPrice"]  else None
                        b3_min  = float(r["MinPrice"])  if r["MinPrice"]  else None
                        b3_max  = float(r["MaxPrice"])  if r["MaxPrice"]  else None
                        b3_qty  = int(float(r["TradeQty"])) if r["TradeQty"] else None
                        b3_found = True
            except Exception as e:
                print(f"  Match error {date_str} {t['rb3_type']}: {e}")

        rows.append({
            **{k: t[k] for k in t.index},
            "b3_ticker":    b3_ticker,
            "b3_style":     b3_style,
            "b3_last":      b3_last,
            "b3_avg":       b3_avg,
            "b3_min":       b3_min,
            "b3_max":       b3_max,
            "b3_qty":       b3_qty,
            "b3_found":     b3_found,
        })
    return pd.DataFrame(rows)


# ── Step 4: Compute metrics ─────────────────────────────────────────────────

def compute_metrics(cmp: pd.DataFrame) -> dict:
    m = {
        "total_targets": len(cmp),
        "b3_found":      int(cmp["b3_found"].sum()),
        "b3_found_pct":  float(cmp["b3_found"].mean() * 100),
    }
    valid = cmp[cmp["b3_found"]].copy()

    # mark vs last (primary gate)
    has_last = valid["b3_last"].notna() & (valid["b3_last"] > 0)
    if has_last.sum() > 0:
        v = valid[has_last]
        diff = (v["rb3_mark"] - v["b3_last"]).abs() / v["b3_last"]
        m["mark_vs_last_match_pct"]   = float((diff < 0.10).mean() * 100)
        m["mark_vs_last_median_diff"] = float(diff.median() * 100)
        m["mark_vs_last_n"]           = int(has_last.sum())
    else:
        m["mark_vs_last_match_pct"] = None

    # mark vs avg (secondary)
    has_avg = valid["b3_avg"].notna() & (valid["b3_avg"] > 0)
    if has_avg.sum() > 0:
        v = valid[has_avg]
        diff = (v["rb3_mark"] - v["b3_avg"]).abs() / v["b3_avg"]
        m["mark_vs_avg_match_pct"] = float((diff < 0.10).mean() * 100)

    # volume
    has_vol = valid["b3_qty"].notna() & (valid["b3_qty"] > 0) & valid["rb3_volume"].notna()
    if has_vol.sum() > 0:
        v = valid[has_vol]
        ratio = v["rb3_volume"] / v["b3_qty"]
        m["volume_ratio_median"]     = float(ratio.median())
        m["volume_within_50pct"]     = float(ratio.between(0.5, 2.0).mean() * 100)

    # bid feasibility: rb3 bid should be ≤ b3 last × 1.05
    has_bid = valid["rb3_bid"].notna() & (valid["rb3_bid"] > 0) & has_last
    if has_bid.sum() > 0:
        v = valid[has_bid]
        m["bid_below_last_pct"] = float(
            (v["rb3_bid"] <= v["b3_last"] * 1.05).mean() * 100
        )

    # ask feasibility: rb3 ask should be ≥ b3 last × 0.95
    has_ask = valid["rb3_ask"].notna() & (valid["rb3_ask"] > 0) & has_last
    if has_ask.sum() > 0:
        v = valid[has_ask]
        m["ask_above_last_pct"] = float(
            (v["rb3_ask"] >= v["b3_last"] * 0.95).mean() * 100
        )

    # spread distribution (from rb3 data)
    has_spread = (
        valid["rb3_bid"].notna() & (valid["rb3_bid"] > 0)
        & valid["rb3_ask"].notna() & (valid["rb3_ask"] > valid["rb3_bid"])
        & valid["rb3_mark"].notna() & (valid["rb3_mark"] > 0)
    )
    if has_spread.sum() > 0:
        v = valid[has_spread]
        spread_pct = (v["rb3_ask"] - v["rb3_bid"]) / v["rb3_mark"]
        m["rb3_spread_median_pct"] = float(spread_pct.median() * 100)
        m["rb3_spread_p75_pct"]    = float(spread_pct.quantile(0.75) * 100)

    # verdict
    match_pct = m.get("mark_vs_last_match_pct")
    if match_pct is None or m["b3_found"] < 5:
        m["verdict"] = "INSUFFICIENT_DATA"
    elif match_pct >= 80:
        m["verdict"] = "PASS"
    elif match_pct >= 50:
        m["verdict"] = "PARTIAL"
    else:
        m["verdict"] = "FAIL"

    return m


# ── Step 5: Exercise style ──────────────────────────────────────────────────

def extract_exercise_style(prod_cache: dict) -> str:
    for date_str in sorted(prod_cache.keys(), reverse=True):
        prod = prod_cache[date_str]
        if prod.empty:
            continue
        bova = prod[prod["Ticker"].str.startswith("BOVA")]
        if bova.empty:
            continue
        styles = bova["Style"].dropna().unique().tolist()
        if styles:
            return f"Styles found on {date_str}: {styles}"
    return "Could not determine — no product data parsed"


# ── Step 6: Write report ────────────────────────────────────────────────────

def write_report(cmp: pd.DataFrame, m: dict, style_info: str) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    path = f"docs/{today} - rb3 price validation.md"
    Path("docs").mkdir(exist_ok=True)

    verdict = m["verdict"]
    with open(path, "w") as f:
        f.write(f"# rb3 Price Validation Against B3 Official Bulletin\n\n")
        f.write(f"**Date:** {today}  \n")
        f.write(f"**Source:** B3 pesquisapregao API (automated, not manual)\n\n---\n\n")
        f.write("## Results\n\n| Metric | Value |\n|--------|-------|\n")
        f.write(f"| Dates checked | {len(VALIDATION_DATES)} |\n")
        f.write(f"| Target contracts | {m['total_targets']} |\n")
        f.write(f"| B3 contracts matched | {m['b3_found']} ({m['b3_found_pct']:.0f}%) |\n")
        if m.get("mark_vs_last_match_pct") is not None:
            f.write(f"| mark vs B3 LastPrice (±10%) | {m['mark_vs_last_match_pct']:.0f}% (n={m.get('mark_vs_last_n','?')}) |\n")
            f.write(f"| Median mark diff | {m.get('mark_vs_last_median_diff','?'):.1f}% |\n")
        if m.get("mark_vs_avg_match_pct") is not None:
            f.write(f"| mark vs B3 AvgPrice (±10%) | {m['mark_vs_avg_match_pct']:.0f}% |\n")
        if m.get("rb3_spread_median_pct") is not None:
            f.write(f"| rb3 implied spread (median) | {m['rb3_spread_median_pct']:.1f}% of mark |\n")
            f.write(f"| rb3 implied spread (P75) | {m['rb3_spread_p75_pct']:.1f}% of mark |\n")
        if m.get("bid_below_last_pct") is not None:
            f.write(f"| rb3 bid ≤ B3 last (feasibility) | {m['bid_below_last_pct']:.0f}% |\n")
        if m.get("ask_above_last_pct") is not None:
            f.write(f"| rb3 ask ≥ B3 last (feasibility) | {m['ask_above_last_pct']:.0f}% |\n")
        f.write(f"\n**Verdict: {verdict}**\n\n")
        f.write("---\n\n## BOVA11 Exercise Style (from B3 Product Bulletin)\n\n")
        f.write(f"{style_info}\n\n")
        f.write("Expected for BOVA11 ETF options: `EURO` (European).\n\n")
        f.write("---\n\n## Interpretation\n\n")
        interp = {
            "PASS": (
                "rb3 mark prices match B3's official last-traded prices within 10%. "
                "The data is sourcing real B3 market quotes. Mid-execution conclusions "
                "from the v7 grid are reliable."
            ),
            "PARTIAL": (
                "rb3 mark prices partially match B3 official data (50-80%). "
                "Some discrepancy — possibly different settlement times or data feeds. "
                "Mid-execution conclusions are directionally valid but treat absolute "
                "Sharpe numbers with added caution."
            ),
            "FAIL": (
                "**CRITICAL:** rb3 mark prices do NOT match B3 official data. "
                "The rb3 database may contain computed/synthetic prices. "
                "STOP — do not proceed to paper trading until this is investigated."
            ),
            "INSUFFICIENT_DATA": (
                "Fewer than 5 contracts were matched. Cannot make a determination. "
                "Check B3 server connectivity and XML parsing for the affected dates."
            ),
        }
        f.write(interp.get(verdict, "Unknown verdict.") + "\n\n")
        f.write("---\n\n## Detailed Comparison\n\n")
        cols = [
            "validation_date", "rb3_type", "rb3_strike", "rb3_expiration",
            "rb3_mark", "rb3_bid", "rb3_ask", "rb3_volume",
            "b3_ticker", "b3_style", "b3_last", "b3_avg",
            "b3_min", "b3_max", "b3_qty", "b3_found",
        ]
        avail = [c for c in cols if c in cmp.columns]
        f.write(cmp[avail].to_markdown(index=False))
        f.write("\n")

    print(f"\nReport written: {path}")
    return path


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("B3 Bulletin vs rb3 Validation")
    print("=" * 60)

    print("\n[1/6] Querying rb3 DB for validation targets...")
    targets = get_rb3_targets(DB_PATH, VALIDATION_DATES)
    if targets.empty:
        print("ERROR: No targets found. Check DB_PATH and date range.")
        sys.exit(1)
    print(f"  {len(targets)} contracts identified across {len(VALIDATION_DATES)} dates")
    targets.to_csv(OUTPUT_DIR / "validation_targets.csv", index=False)

    print("\n[2/6] Downloading B3 official bulletins...")
    print("  (20 HTTP requests, 0.5s sleep between each — ~15 min total)")
    neg_cache, prod_cache = fetch_all_bulletins(VALIDATION_DATES)

    print("\n[3/6] Matching contracts...")
    cmp = match_contracts(targets, neg_cache, prod_cache)
    cmp.to_csv(OUTPUT_DIR / "validation_comparison.csv", index=False)
    print(f"  Matched {cmp['b3_found'].sum()} of {len(cmp)}")

    print("\n[4/6] Computing metrics...")
    m = compute_metrics(cmp)
    for k, v in m.items():
        if v is not None:
            s = f"{v:.1f}" if isinstance(v, float) else str(v)
            print(f"  {k}: {s}")

    print("\n[5/6] Extracting exercise style...")
    style_info = extract_exercise_style(prod_cache)
    print(f"  {style_info}")

    print("\n[6/6] Writing report...")
    write_report(cmp, m, style_info)

    print(f"\n{'='*60}")
    print(f"VERDICT: {m['verdict']}")
    print(f"{'='*60}")

    if m["verdict"] == "FAIL":
        print("\nCRITICAL: rb3 prices do not match B3 official data.")
        print("Do NOT proceed to Steps 2 or 6 until this is resolved.")
        sys.exit(1)
    elif m["verdict"] == "INSUFFICIENT_DATA":
        print("\nWARNING: Not enough contracts matched for a reliable verdict.")
        print("Check the detailed comparison CSV and report to user.")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
```

#### Run it

```bash
python scripts/validate_b3_prices.py
```

**STOP here if exit code is 1.** Report the verdict and comparison CSV to the user
before running Steps 2 and 6.

---

## Step 2 — Extended Commission Sensitivity

### Why

The v7 commission sensitivity tested 1×, 2×, 3× baseline (R$2.00/trade). The
comprehensive report explicitly flags that B3 retail commissions can be R$5-20/contract,
making the tested range too conservative. Retail commissions at R$10/contract are
approximately 5× baseline — outside the existing tests.

### Task

Extend the commission sensitivity script to test through 10× baseline for the
top 5 configs across all 3 execution modes.

Create or extend `scripts/extended_commission_sensitivity.py`:

```python
"""
Extended commission sensitivity analysis for the top 5 v7 BOVA11 configs.
Tests commission multipliers 1×, 2×, 3×, 5×, 7×, 10× of R$2.00 baseline.
Covers both BOVA11 and PETR4 recommended configs.

Output:
  output/commission_extended/bova11_commission_extended.csv
  output/commission_extended/petr4_commission_extended.csv
  docs/YYYY-MM-DD - extended commission sensitivity.md
"""

import sys
from pathlib import Path
from datetime import datetime

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from straddle.params import PARAMS, apply_market_preset
from straddle.data import load_market_data
from straddle.engines import make_engine
from straddle.portfolio import run_portfolio_backtest
from straddle.metrics import compute_portfolio_metrics

OUTPUT_DIR = Path("output/commission_extended")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

BASELINE_COMMISSION = 2.00   # R$ per trade (institutional)

# Commission multipliers to test
MULTIPLIERS = [1, 2, 3, 5, 7, 10]

# Top 5 stable BOVA11 configs (from v7 Cell K stability rank)
BOVA11_CONFIGS = [
    {"target_delta": 0.25, "dte_max": 21, "profit_target_pct": 0.50,
     "manage_at_dte": 14, "vix_filter": "OFF",       "stop_loss_pct": 2.0},
    {"target_delta": 0.25, "dte_max": 21, "profit_target_pct": 0.50,
     "manage_at_dte": 14, "vix_filter": "rv_pct:80", "stop_loss_pct": 2.0},
    {"target_delta": 0.20, "dte_max": 21, "profit_target_pct": 0.50,
     "manage_at_dte": 14, "vix_filter": "OFF",       "stop_loss_pct": 2.0},
    {"target_delta": 0.20, "dte_max": 21, "profit_target_pct": 0.50,
     "manage_at_dte": 14, "vix_filter": "rv_pct:80", "stop_loss_pct": 3.0},
    {"target_delta": 0.16, "dte_max": 21, "profit_target_pct": 0.50,
     "manage_at_dte": 14, "vix_filter": "rv_pct:70", "stop_loss_pct": 3.0},
]

PETR4_CONFIGS = [
    {"target_delta": 0.25, "dte_max": 21, "profit_target_pct": 0.50,
     "manage_at_dte": 14, "vix_filter": "OFF",       "stop_loss_pct": 2.0},
    {"target_delta": 0.25, "dte_max": 21, "profit_target_pct": 0.50,
     "manage_at_dte": 14, "vix_filter": "rv_pct:80", "stop_loss_pct": 2.0},
    {"target_delta": 0.20, "dte_max": 21, "profit_target_pct": 0.50,
     "manage_at_dte": 14, "vix_filter": "OFF",       "stop_loss_pct": 2.0},
]

MODES = ["bid_ask", "mid", "mid_plus_1tick"]

RUNS = [
    ("train",   "2018-01-02", "2022-12-30"),
    ("holdout", "2023-01-02", "2025-11-30"),
]


def run_one(market: str, config: dict, mode: str, period: str,
            start: str, end: str, commission: float) -> dict:
    params = dict(PARAMS)
    apply_market_preset(params, market)
    params.update({
        "mode": "market",
        "start_date": start, "end_date": end,
        "portfolio_mode": "laddering",
        "cash_investment_mode": "risk_free",
        "cash_yield_annual": 0.0,
        "execution_mode": mode,
        "commission_per_contract": commission,
        **config,
    })
    data = load_market_data(start, end, market=market)
    engine = make_engine(params)
    trades, eq = run_portfolio_backtest(data, params, engine)
    m = compute_portfolio_metrics(trades, eq, params, data)
    return {
        "market": market,
        "period": period,
        "execution_mode": mode,
        "commission": commission,
        "commission_multiplier": commission / BASELINE_COMMISSION,
        "config_label": (
            f"{int(config['target_delta']*100)}δ"
            f"/dte{config['dte_max']}"
            f"/pt{int(config['profit_target_pct']*100)}%"
            f"/{config.get('vix_filter','OFF')}"
        ),
        **{k: v for k, v in config.items()},
        "sharpe":       m.get("sharpe", None),
        "total_return": m.get("total_return", None),
        "n_trades":     m.get("n_trades", None),
        "max_drawdown": m.get("max_drawdown", None),
    }


def main():
    all_rows = []

    for market, configs in [("bova11", BOVA11_CONFIGS), ("petr4", PETR4_CONFIGS)]:
        print(f"\n{'='*50}")
        print(f"Market: {market.upper()}")
        n = len(configs) * len(MODES) * len(MULTIPLIERS) * len(RUNS)
        print(f"Running {n} backtests...")

        for cfg in configs:
            for mode in MODES:
                for mult in MULTIPLIERS:
                    commission = BASELINE_COMMISSION * mult
                    for period, start, end in RUNS:
                        label = f"{cfg['target_delta']}δ/{mode}/commission={mult}×/{period}"
                        print(f"  {label}", end="... ", flush=True)
                        try:
                            row = run_one(market, cfg, mode, period, start, end, commission)
                            all_rows.append(row)
                            print(f"Sharpe={row['sharpe']:.2f}" if row['sharpe'] else "n/a")
                        except Exception as e:
                            print(f"ERROR: {e}")
                            all_rows.append({
                                "market": market, "period": period,
                                "execution_mode": mode,
                                "commission": commission,
                                "commission_multiplier": mult,
                                "config_label": str(cfg),
                                "sharpe": None, "error": str(e),
                            })

    df = pd.DataFrame(all_rows)

    # Split and save
    for market in ["bova11", "petr4"]:
        sub = df[df["market"] == market]
        sub.to_csv(OUTPUT_DIR / f"{market}_commission_extended.csv", index=False)

    # Write report
    today = datetime.now().strftime("%Y-%m-%d")
    report_path = f"docs/{today} - extended commission sensitivity.md"
    with open(report_path, "w") as f:
        f.write("# Extended Commission Sensitivity — BOVA11 & PETR4\n\n")
        f.write(f"**Date:** {today}  \n")
        f.write(f"**Baseline commission:** R${BASELINE_COMMISSION:.2f}/trade  \n")
        f.write(f"**Multipliers tested:** {MULTIPLIERS}  \n")
        f.write(f"  (5× = R${BASELINE_COMMISSION*5:.2f}, ~mid-range retail)  \n")
        f.write(f"  (10× = R${BASELINE_COMMISSION*10:.2f}, ~expensive retail)\n\n")

        f.write("---\n\n")

        for market in ["bova11", "petr4"]:
            sub = df[df["market"] == market]
            f.write(f"## {market.upper()}\n\n")

            # Holdout pivot: config × commission multiplier for mid execution
            hold_mid = sub[
                (sub["period"] == "holdout") &
                (sub["execution_mode"] == "mid")
            ]
            if not hold_mid.empty:
                pivot = hold_mid.pivot_table(
                    index="config_label",
                    columns="commission_multiplier",
                    values="sharpe",
                    aggfunc="first",
                )
                f.write("### Holdout Sharpe at `mid` execution\n\n")
                f.write(pivot.round(2).to_markdown())
                f.write("\n\n")

                # Find break-even multiplier per config
                f.write("### Break-even commission multiplier (holdout, mid)\n\n")
                f.write("| Config | Last positive | Sharpe at 10× |\n|--------|-------------|---------------|\n")
                for cfg_label, row in pivot.iterrows():
                    positive_mults = [m for m in MULTIPLIERS if row.get(m, -999) > 0]
                    last_pos = max(positive_mults) if positive_mults else "none"
                    sharpe_10x = row.get(10, None)
                    sharpe_str = f"{sharpe_10x:.2f}" if sharpe_10x is not None else "n/a"
                    f.write(f"| {cfg_label} | {last_pos}× | {sharpe_str} |\n")
                f.write("\n")

            # Execution mode comparison at highest multiplier (10×) for best config
            hold_10x = sub[
                (sub["period"] == "holdout") &
                (sub["commission_multiplier"] == 10)
            ]
            if not hold_10x.empty:
                f.write("### Holdout Sharpe at 10× commission by execution mode\n\n")
                pivot_mode = hold_10x.pivot_table(
                    index="config_label",
                    columns="execution_mode",
                    values="sharpe",
                    aggfunc="first",
                )
                f.write(pivot_mode.round(2).to_markdown())
                f.write("\n\n")

    print(f"\nReport: {report_path}")
    return df


if __name__ == "__main__":
    df = main()
    print("Done.")
```

#### Run it

```bash
python scripts/extended_commission_sensitivity.py
```

**Expected runtime:** ~20 minutes (180 backtests: 5+3 configs × 3 modes × 6 multipliers × 2 periods).

---

## Step 6 — PETR4 Period Robustness

### Why

PETR4's train/holdout asymmetry (25.8% positive at mid in train vs 76.9% in holdout)
makes the "PETR4 VRP confirmed" headline questionable. Before deploying PETR4 capital,
the same 5-window period robustness check done for BOVA11 must be done for PETR4.
The BOVA11 check showed 100% config profitability in all 3 data-rich windows (2018-2024);
PETR4 has DB coverage back to 2017, so 4 of the 5 windows should have decent coverage.

### Task

Create `scripts/petr4_period_robustness.py` following exactly the same methodology
as the BOVA11 period robustness from Phase 6 of Plan 014, applied to PETR4.

```python
"""
PETR4 period robustness analysis.
Mirrors the BOVA11 robustness from v7 Phase 6.

15 top PETR4 configs × 5 rolling 3-year windows × 3 execution modes = 225 backtests.

Windows:
  2015-01-02 to 2017-12-29  (low DB coverage expected)
  2016-01-04 to 2018-12-31  (moderate DB coverage)
  2018-01-02 to 2020-12-31  (good coverage)
  2020-01-02 to 2022-12-30  (good coverage)
  2022-01-03 to 2024-12-31  (full coverage)

Output:
  output/petr4_robustness/petr4_robustness_results.csv
  docs/YYYY-MM-DD - PETR4 period robustness.md
"""

import sys
from pathlib import Path
from datetime import datetime

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from straddle.params import PARAMS, apply_market_preset
from straddle.data import load_market_data
from straddle.engines import make_engine
from straddle.portfolio import run_portfolio_backtest
from straddle.metrics import compute_portfolio_metrics

OUTPUT_DIR = Path("output/petr4_robustness")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MODES = ["bid_ask", "mid", "mid_plus_1tick"]

WINDOWS = [
    ("2015-2017", "2015-01-02", "2017-12-29"),
    ("2016-2018", "2016-01-04", "2018-12-31"),
    ("2018-2020", "2018-01-02", "2020-12-31"),
    ("2020-2022", "2020-01-02", "2022-12-30"),
    ("2022-2024", "2022-01-03", "2024-12-31"),
]

# Top 15 PETR4 configs from v7 grid
# These should be the top 15 by min(train_sharpe, holdout_sharpe) at mid.
# If you have the PETR4 v7 parquet, derive them programmatically.
# Otherwise use these (the equivalent of the BOVA11 top stable configs, applied to PETR4):

def get_top_petr4_configs(n: int = 15) -> list[dict]:
    """Load top N stable PETR4 configs from v7 parquet."""
    parquet_path = Path("data/B3/v7_petr4_grid_search_results.parquet")
    if not parquet_path.exists():
        raise FileNotFoundError(f"PETR4 v7 parquet not found: {parquet_path}")

    df = pd.read_parquet(parquet_path)
    valid = df[df["error"].isna() & (df["n_trades"] >= 30)].copy()

    # Only mid mode for ranking
    mid = valid[valid["execution_mode"] == "mid"]
    train = mid[mid["period_label"] == "train"].set_index(
        ["target_delta", "dte_max", "profit_target_pct",
         "manage_at_dte", "vix_filter", "stop_loss_pct"]
    )["sharpe"].rename("train_sharpe")
    hold = mid[mid["period_label"] == "holdout"].set_index(
        ["target_delta", "dte_max", "profit_target_pct",
         "manage_at_dte", "vix_filter", "stop_loss_pct"]
    )["sharpe"].rename("holdout_sharpe")

    both = pd.concat([train, hold], axis=1).dropna()
    both["stability"] = both[["train_sharpe", "holdout_sharpe"]].min(axis=1)
    both = both.sort_values("stability", ascending=False)

    top = both.head(n).reset_index()
    configs = []
    for _, row in top.iterrows():
        configs.append({
            "target_delta":      row["target_delta"],
            "dte_max":           row["dte_max"],
            "profit_target_pct": row["profit_target_pct"],
            "manage_at_dte":     row["manage_at_dte"],
            "vix_filter":        row["vix_filter"],
            "stop_loss_pct":     row["stop_loss_pct"],
            "_stability":        row["stability"],
        })
    return configs


def run_one(config: dict, mode: str, window_name: str,
            start: str, end: str) -> dict:
    params = dict(PARAMS)
    apply_market_preset(params, "petr4")
    cfg = {k: v for k, v in config.items() if not k.startswith("_")}
    params.update({
        "mode": "market",
        "start_date": start, "end_date": end,
        "portfolio_mode": "laddering",
        "cash_investment_mode": "risk_free",
        "cash_yield_annual": 0.0,
        "execution_mode": mode,
        **cfg,
    })
    data = load_market_data(start, end, market="petr4")
    engine = make_engine(params)
    trades, eq = run_portfolio_backtest(data, params, engine)
    m = compute_portfolio_metrics(trades, eq, params, data)
    return {
        "window":           window_name,
        "execution_mode":   mode,
        "target_delta":     config["target_delta"],
        "dte_max":          config["dte_max"],
        "profit_target_pct":config["profit_target_pct"],
        "manage_at_dte":    config["manage_at_dte"],
        "vix_filter":       config["vix_filter"],
        "stop_loss_pct":    config["stop_loss_pct"],
        "stability_rank":   config.get("_stability", None),
        "sharpe":           m.get("sharpe", None),
        "total_return":     m.get("total_return", None),
        "max_drawdown":     m.get("max_drawdown", None),
        "n_trades":         m.get("n_trades", None),
        "entry_db_pct":     m.get("entry_db_pct", None),
    }


def main():
    print("=" * 60)
    print("PETR4 Period Robustness (225 backtests)")
    print("=" * 60)

    print("\nLoading top 15 PETR4 configs from v7 parquet...")
    configs = get_top_petr4_configs(15)
    print(f"  {len(configs)} configs loaded")

    n_total = len(configs) * len(WINDOWS) * len(MODES)
    print(f"\nRunning {n_total} backtests...")

    rows = []
    done = 0
    for cfg in configs:
        for window_name, start, end in WINDOWS:
            for mode in MODES:
                done += 1
                label = (f"{cfg['target_delta']}δ/"
                         f"dte{cfg['dte_max']}/"
                         f"{mode}/"
                         f"{window_name}")
                print(f"  [{done}/{n_total}] {label}", end="... ", flush=True)
                try:
                    row = run_one(cfg, mode, window_name, start, end)
                    rows.append(row)
                    s = row["sharpe"]
                    db = row["entry_db_pct"]
                    print(
                        f"Sharpe={s:.2f}"
                        + (f" (DB={db:.0f}%)" if db else "")
                        if s is not None else "n/a"
                    )
                except Exception as e:
                    print(f"ERROR: {e}")
                    rows.append({
                        "window": window_name, "execution_mode": mode,
                        "target_delta": cfg["target_delta"],
                        "sharpe": None, "error": str(e),
                    })

    df = pd.DataFrame(rows)
    df.to_csv(OUTPUT_DIR / "petr4_robustness_results.csv", index=False)

    # ── Summary tables ─────────────────────────────────────────────────────

    today = datetime.now().strftime("%Y-%m-%d")
    report_path = f"docs/{today} - PETR4 period robustness.md"
    with open(report_path, "w") as f:
        f.write("# PETR4 Period Robustness\n\n")
        f.write(f"**Date:** {today}  \n")
        f.write(f"**Configs:** 15 top stable from v7  \n")
        f.write(f"**Windows:** 5 rolling 3-year periods 2015-2024  \n")
        f.write(f"**Total backtests:** {len(df)}\n\n---\n\n")

        # Overall by execution mode
        f.write("## Overall (all windows, all configs)\n\n")
        f.write("| Mode | % Positive | Median Sharpe | Plan target |\n")
        f.write("|------|-----------|--------------|------------|\n")
        targets_map = {"bid_ask": "<50%", "mid": ">50%", "mid_plus_1tick": ">70%"}
        for mode in MODES:
            sub = df[df["execution_mode"] == mode]["sharpe"].dropna()
            pct_pos = (sub > 0).mean() * 100
            med = sub.median()
            tgt = targets_map.get(mode, "")
            f.write(f"| {mode} | {pct_pos:.1f}% | {med:.3f} | {tgt} |\n")

        # By window, mid only
        f.write("\n## By Window (mid execution)\n\n")
        f.write("| Window | % Positive | Median Sharpe | DB Coverage |\n")
        f.write("|--------|-----------|--------------|-------------|\n")
        for window_name, _, _ in WINDOWS:
            sub = df[(df["window"] == window_name) & (df["execution_mode"] == "mid")]
            sharpes = sub["sharpe"].dropna()
            pct_pos = (sharpes > 0).mean() * 100
            med = sharpes.median()
            db_pct = sub["entry_db_pct"].dropna().mean()
            db_str = f"{db_pct:.1f}%" if not pd.isna(db_pct) else "n/a"
            f.write(f"| {window_name} | {pct_pos:.1f}% | {med:.3f} | {db_str} |\n")

        # Recommended config (25δ/dte21/pt50%) across all windows
        f.write("\n## Recommended Config (25δ/dte21/pt50%/OFF) by Window\n\n")
        f.write("| Window | bid_ask | mid | mid_plus_1tick | DB% |\n")
        f.write("|--------|---------|-----|----------------|-----|\n")
        rec = df[
            (df["target_delta"] == 0.25)
            & (df["dte_max"] == 21)
            & (df["profit_target_pct"] == 0.50)
            & (df["vix_filter"] == "OFF")
            & (df["stop_loss_pct"] == 2.0)
        ]
        for window_name, _, _ in WINDOWS:
            row_data = {}
            db_pct = None
            for mode in MODES:
                sub = rec[(rec["window"] == window_name) & (rec["execution_mode"] == mode)]
                row_data[mode] = f"{sub['sharpe'].values[0]:.2f}" if len(sub) > 0 and sub["sharpe"].notna().any() else "n/a"
                if mode == "mid" and len(sub) > 0:
                    db_pct = sub["entry_db_pct"].values[0]
            db_str = f"{db_pct:.0f}%" if db_pct is not None and not pd.isna(db_pct) else "n/a"
            f.write(
                f"| {window_name} | {row_data.get('bid_ask','n/a')} "
                f"| {row_data.get('mid','n/a')} "
                f"| {row_data.get('mid_plus_1tick','n/a')} "
                f"| {db_str} |\n"
            )

        # Conclusion
        mid_df = df[df["execution_mode"] == "mid"]["sharpe"].dropna()
        overall_pct = (mid_df > 0).mean() * 100
        data_rich_windows = ["2018-2020", "2020-2022", "2022-2024"]
        rich_sub = df[
            df["window"].isin(data_rich_windows)
            & (df["execution_mode"] == "mid")
        ]["sharpe"].dropna()
        rich_pct = (rich_sub > 0).mean() * 100

        f.write(f"\n## Conclusion\n\n")
        f.write(f"- Overall (mid): {overall_pct:.1f}% configs positive across all windows\n")
        f.write(f"- Data-rich windows (2018-2024): {rich_pct:.1f}% configs positive at mid\n")

        bova11_target = 78.7  # from v7 report
        if rich_pct >= 90:
            f.write(f"- **PETR4 is as robust as BOVA11** ({rich_pct:.1f}% vs BOVA11 {bova11_target}% in data-rich windows)\n")
        elif rich_pct >= 70:
            f.write(f"- **PETR4 is moderately robust** ({rich_pct:.1f}% vs BOVA11 {bova11_target}%)  \n")
            f.write("  Consider starting BOVA11 first; add PETR4 after fill quality is confirmed.\n")
        else:
            f.write(f"- **PETR4 is less robust than BOVA11** ({rich_pct:.1f}% vs {bova11_target}%)  \n")
            f.write("  Recommend NOT deploying PETR4 capital until further investigation.\n")

    print(f"\nReport: {report_path}")
    return df


if __name__ == "__main__":
    df = main()
    print("\nDone.")
```

#### Run it

```bash
python scripts/petr4_period_robustness.py
```

**Expected runtime:** ~25 minutes (225 backtests with laddering).

---

## Definition of Done

The task is complete when ALL of the following exist:

**Step 1:**

- [ ] `scripts/b3_bulletin_fetcher.py` — B3 downloader/parser
- [ ] `scripts/validate_b3_prices.py` — comparison script
- [ ] `output/validation/validation_targets.csv`
- [ ] `output/validation/validation_comparison.csv`
- [ ] `docs/YYYY-MM-DD - rb3 price validation.md` — includes PASS/PARTIAL/FAIL verdict
      and BOVA11 exercise style from B3 official data
- [ ] Script exited with code 0 (PASS or PARTIAL)

**Step 2:**

- [ ] `scripts/extended_commission_sensitivity.py`
- [ ] `output/commission_extended/bova11_commission_extended.csv`
- [ ] `output/commission_extended/petr4_commission_extended.csv`
- [ ] `docs/YYYY-MM-DD - extended commission sensitivity.md` — includes break-even
      multiplier per config per mode, and Sharpe at 10× for all configs

**Step 6:**

- [ ] `scripts/petr4_period_robustness.py`
- [ ] `output/petr4_robustness/petr4_robustness_results.csv`
- [ ] `docs/YYYY-MM-DD - PETR4 period robustness.md` — includes overall % positive,
      by-window table, and a clear conclusion on whether PETR4 is deploy-ready

**All steps:**

- [ ] All existing tests still pass (`pytest tests/ -v`)
- [ ] Git commit with message: `"feat: B3 bulletin validation, extended commissions, PETR4 robustness"`

---

## Deviations allowed

- **Step 1:** If fewer than 5 dates return B3 data (HTTP failures), report which dates
  failed and run the verdict on whatever data was obtained. Do not abort.
- **Step 1:** If the B3 XML schema on some dates differs (field names changed between
  2018 and 2025), handle the difference gracefully with try/except and log which dates
  parsed successfully.
- **Step 2:** If the PETR4 v7 parquet doesn't exist when Step 6 runs, substitute the
  3 PETR4 configs listed in the script above as a hardcoded fallback.
- **Step 6:** If the 2015-2017 window has <15% DB coverage for PETR4, flag it in the
  report as "synthetic-dominant, not reliable" but still include the numbers for completeness.
- **Runtime:** If Step 6 sequential runtime exceeds 45 minutes, reduce to the top 10
  configs (drop the bottom 5 by stability rank) and note the reduction in the report.
