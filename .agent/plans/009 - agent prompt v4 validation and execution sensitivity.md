# Agent Task: B3 Official Bulletin Bid/Ask Validation + V4 Execution Sensitivity

## Context

We are building a systematic short strangle backtest for BOVA11 (Brazilian ETF options).
The v3 grid search showed deeply negative Sharpe across 7,560 configurations using
"sell at bid, buy at ask" execution. This contradicts established Brazilian VRP literature.

The key question: are the `bid` and `ask` columns in `data/B3/b3_options_rb3.db`
real published quotes, or computed estimates? If computed, the entire bid/ask analysis
is invalid.

We have found a free, authoritative validation source: B3's official daily bulletin API,
scraped by `https://github.com/renanikeda/options-pricing/blob/main/data/B3_options.py`.
All dates from 2018-2025 are confirmed accessible (HTTP 200, application/octet-stream).

This task has two parts:
1. **Validate rb3 bid/ask data against B3's official bulletin** (the blocker)
2. **Implement the v4 execution sensitivity grid** (the main research deliverable)

Do them in order. Document findings clearly. If Part 1 finds a critical issue (rb3 prices
don't match B3's official data), STOP and report before running Part 2.

---

## Part 1: B3 Official Bulletin Validation

### What you're building

A validation script that:
1. Downloads B3's official daily bulletins for 10 specific dates
2. Parses them to get official B3 last-traded prices and volumes for target BOVA11 options
3. Compares against rb3's database values
4. Produces a pass/fail verdict with supporting data

### Step 1.1 — Install/copy the B3 bulletin fetcher

Copy the fetcher code from the GitHub repo into your project. Create
`scripts/b3_bulletin_fetcher.py` with the following content (taken verbatim from
`https://github.com/renanikeda/options-pricing/blob/main/data/B3_options.py`):

```python
# scripts/b3_bulletin_fetcher.py
# Sourced from: https://github.com/renanikeda/options-pricing/blob/main/data/B3_options.py
# Fetches B3 official daily bulletins and parses negotiation + product XML data.

import requests
import zipfile
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Literal
import os
from time import sleep
import shutil


def parse_xml(xml_path: str):
    try:
        tree = ET.parse(xml_path)
        return tree.getroot()
    except (ET.ParseError, IOError) as e:
        print(f"Error parsing XML: {e}")
        return None


def parse_products_xml_to_df(xml_path: str) -> pd.DataFrame:
    root = parse_xml(xml_path)
    if root is None:
        return pd.DataFrame()
    ns = {
        "bvmf052": "urn:bvmf.052.01.xsd",
        "head": "urn:iso:std:iso:20022:tech:xsd:head.001.001.01",
        "bvmf100": "urn:bvmf.100.02.xsd",
    }
    rows = []
    for pricrpt in root.findall(".//bvmf100:Instrm", ns):
        record = {}
        record["Ticker"] = pricrpt.findtext(
            "bvmf100:InstrmInf/bvmf100:OptnOnEqtsInf/bvmf100:TckrSymb", namespaces=ns
        )
        if not record["Ticker"]:
            continue
        record["Ação"] = pricrpt.findtext(
            "bvmf100:FinInstrmAttrCmon/bvmf100:Asst", namespaces=ns
        )
        record["ID_ação"] = pricrpt.findtext(
            "bvmf100:InstrmInf/bvmf100:OptnOnEqtsInf/bvmf100:UndrlygInstrmId/bvmf100:OthrId/bvmf100:Id",
            namespaces=ns,
        )
        record["Style"] = pricrpt.findtext(
            "bvmf100:InstrmInf/bvmf100:OptnOnEqtsInf/bvmf100:OptnStyle", namespaces=ns
        )
        record["Type"] = pricrpt.findtext(
            "bvmf100:InstrmInf/bvmf100:OptnOnEqtsInf/bvmf100:OptnTp", namespaces=ns
        )
        record["Strike"] = pricrpt.findtext(
            "bvmf100:InstrmInf/bvmf100:OptnOnEqtsInf/bvmf100:ExrcPric", namespaces=ns
        )
        record["Maturity"] = pricrpt.findtext(
            "bvmf100:InstrmInf/bvmf100:OptnOnEqtsInf/bvmf100:XprtnDt", namespaces=ns
        )
        record["Descrição"] = pricrpt.findtext(
            "bvmf100:FinInstrmAttrCmon/bvmf100:Desc", namespaces=ns
        )
        rows.append(record)
    return pd.DataFrame(rows)


def parse_negotiation_xml_to_df(xml_path: str) -> pd.DataFrame:
    root = parse_xml(xml_path)
    if root is None:
        return pd.DataFrame()
    ns = {
        "bvmf052": "urn:bvmf.052.01.xsd",
        "head": "urn:iso:std:iso:20022:tech:xsd:head.001.001.01",
        "bvmf217": "urn:bvmf.217.01.xsd",
    }
    rows = []
    for pricrpt in root.findall(".//bvmf217:PricRpt", ns):
        record = {}
        record["ID"] = pricrpt.findtext(
            "bvmf217:FinInstrmId/bvmf217:OthrId/bvmf217:Id", namespaces=ns
        )
        record["TradeDate"] = pricrpt.findtext(
            "bvmf217:TradDt/bvmf217:Dt", namespaces=ns
        )
        record["Ticker"] = pricrpt.findtext(
            "bvmf217:SctyId/bvmf217:TckrSymb", namespaces=ns
        )
        record["FirstPrice"] = pricrpt.findtext(
            "bvmf217:FinInstrmAttrbts/bvmf217:FrstPric", namespaces=ns
        )
        if not record["FirstPrice"]:
            continue
        record["MinPrice"] = pricrpt.findtext(
            "bvmf217:FinInstrmAttrbts/bvmf217:MinPric", namespaces=ns
        )
        record["MaxPrice"] = pricrpt.findtext(
            "bvmf217:FinInstrmAttrbts/bvmf217:MaxPric", namespaces=ns
        )
        record["LastPrice"] = pricrpt.findtext(
            "bvmf217:FinInstrmAttrbts/bvmf217:LastPric", namespaces=ns
        )
        record["AvgPrice"] = pricrpt.findtext(
            "bvmf217:FinInstrmAttrbts/bvmf217:TradAvrgPric", namespaces=ns
        )
        record["TradeQty"] = pricrpt.findtext(
            "bvmf217:TradDtls/bvmf217:TradQty", namespaces=ns
        )
        rows.append(record)
    return pd.DataFrame(rows)


def download_and_save_zipfile(file_code: str, save_path: str = None) -> str | None:
    headers = {
        "referer": (
            "https://www.b3.com.br/pt_br/market-data-e-indices/servicos-de-dados/"
            "market-data/historico/boletins-diarios/pesquisa-por-pregao/"
            "pesquisa-por-pregao/"
        ),
    }
    url = f"https://www.b3.com.br/pesquisapregao/download?filelist={file_code}.zip,"
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        if save_path is None:
            save_path = f"{file_code}.zip"
        elif os.path.isdir(save_path):
            save_path = os.path.join(save_path, f"{file_code}.zip")
        os.makedirs(
            os.path.dirname(save_path) if os.path.dirname(save_path) else ".",
            exist_ok=True,
        )
        with open(save_path, "wb") as f:
            f.write(response.content)
        return save_path
    except Exception as e:
        print(f"Error downloading {file_code}: {e}")
        return None


def unzip_file(zip_path: str, extract_to: str = None, remove_zip: bool = True):
    try:
        if extract_to is None:
            extract_to = os.path.dirname(zip_path) or "."
        extracted_files = []
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(extract_to)
            for filename in zip_ref.namelist():
                extracted_path = os.path.join(extract_to, filename)
                if ".zip" in extracted_path:
                    nested = unzip_file(
                        extracted_path,
                        "/".join(extracted_path.split("/")[:-1]),
                    )
                    if isinstance(nested, list):
                        extracted_files.extend(nested)
                    else:
                        extracted_files.append(nested)
                else:
                    extracted_files.append(extracted_path)
        if remove_zip:
            os.remove(zip_path)
        return extracted_files
    except zipfile.BadZipFile:
        raise
    except IOError as e:
        print(f"Error extracting: {e}")
        return None


def get_b3_daily(
    date_str: str,
    output_dir: str = "/tmp/b3_bulletins",
    type: Literal["negotiation", "product"] = "negotiation",
    retries: int = 0,
) -> pd.DataFrame:
    """
    Fetch B3 daily bulletin for a given date (format: YYYYMMDD).
    type='negotiation' returns traded prices; type='product' returns contract specs.
    """
    try:
        prefix = "PR" if type == "negotiation" else "IN"
        code = prefix + date_str[2:]  # e.g. 20200316 → PR200316
        os.makedirs(output_dir, exist_ok=True)
        zip_path = download_and_save_zipfile(code, output_dir)
        if not zip_path:
            return pd.DataFrame()
        extracted = unzip_file(zip_path, os.path.join(output_dir, code))
        if not extracted:
            return pd.DataFrame()
        xml_file = next((f for f in extracted if f.endswith(".xml")), None)
        if not xml_file:
            return pd.DataFrame()
        if type == "negotiation":
            df = parse_negotiation_xml_to_df(xml_file)
        else:
            df = parse_products_xml_to_df(xml_file)
        # cleanup
        shutil.rmtree(os.path.join(output_dir, code), ignore_errors=True)
        return df
    except zipfile.BadZipFile:
        if retries >= 3:
            return pd.DataFrame()
        sleep(0.5 * (retries + 1))
        return get_b3_daily(date_str, output_dir, type, retries + 1)
    except Exception as e:
        print(f"Error for {date_str}: {e}")
        return pd.DataFrame()
```

### Step 1.2 — Build the validation script

Create `scripts/validate_b3_prices.py`:

```python
"""
Validate rb3 database prices against B3's official daily bulletin data.

For 10 specific dates, this script:
1. Queries rb3 DB for the BOVA11 option closest to 16-delta put and call
   at the next monthly expiration
2. Downloads B3's official daily bulletin for that date
3. Compares rb3 mark/close vs B3 LastPrice and AvgPrice
4. Compares rb3 volume vs B3 TradeQty
5. Produces a PASS/PARTIAL/FAIL verdict

Also extracts the official B3 option exercise style (European/American) for BOVA11.

Output files:
  output/validation/validation_targets.csv     — rb3 data for target contracts
  output/validation/validation_b3_official.csv — B3 bulletin data for same contracts
  output/validation/validation_comparison.csv  — side-by-side comparison + verdict
  docs/YYYY-MM-DD - rb3 price validation.md    — human-readable report
"""

import sqlite3
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
import sys
import os

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.b3_bulletin_fetcher import get_b3_daily

# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────

DB_PATH = "data/B3/b3_options_rb3.db"
OUTPUT_DIR = Path("output/validation")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 10 validation dates — spread across different market regimes
VALIDATION_DATES = [
    "20180615",   # Normal 2018 trading
    "20190412",   # Normal 2019 trading
    "20200316",   # COVID crash (worst-case spreads)
    "20200915",   # Mid-COVID recovery (high vol, stable)
    "20210512",   # Post-vaccine normal
    "20220831",   # Pre-election 2022
    "20221031",   # Lula election day
    "20230815",   # Normal 2023
    "20241015",   # Recent control date
    "20250110",   # Recent 2025
]

# ─────────────────────────────────────────────
# Step 1: Query rb3 DB for validation targets
# ─────────────────────────────────────────────

def get_rb3_targets(db_path: str, validation_dates: list[str]) -> pd.DataFrame:
    """
    For each validation date, find the BOVA11 option closest to 16-delta
    put and call at the next monthly expiration.
    Returns one put row and one call row per date (up to 20 rows total).
    """
    conn = sqlite3.connect(db_path)
    targets = []

    for date_str in validation_dates:
        date_fmt = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"  # YYYY-MM-DD

        for opt_type, target_delta in [("put", -0.16), ("call", 0.16)]:
            # Find closest to 16-delta at next monthly expiration
            query = """
                SELECT
                    date, expiration, type, strike,
                    mark, bid, ask, volume,
                    delta, implied_volatility
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
            row = pd.read_sql(query, conn, params=(date_fmt, opt_type, target_delta))
            if not row.empty:
                row["validation_date"] = date_str
                targets.append(row)

    conn.close()
    if not targets:
        return pd.DataFrame()

    df = pd.concat(targets, ignore_index=True)
    df.columns = [
        "rb3_date", "rb3_expiration", "rb3_type", "rb3_strike",
        "rb3_mark", "rb3_bid", "rb3_ask", "rb3_volume",
        "rb3_delta", "rb3_iv", "validation_date"
    ]
    return df


# ─────────────────────────────────────────────
# Step 2: Fetch B3 official data for each date
# ─────────────────────────────────────────────

def fetch_b3_official(targets_df: pd.DataFrame) -> pd.DataFrame:
    """
    For each unique validation date in targets_df, download B3's official
    bulletin and return negotiation records for BOVA-related tickers.
    Caches by date to avoid re-downloading.
    """
    results = []
    seen_dates = {}

    for _, row in targets_df.iterrows():
        date_str = row["validation_date"]

        if date_str not in seen_dates:
            print(f"  Fetching B3 bulletin for {date_str}...")
            neg_df = get_b3_daily(date_str, type="negotiation")

            if not neg_df.empty:
                # Filter to BOVA options
                bova_df = neg_df[neg_df["Ticker"].str.startswith("BOVA", na=False)].copy()
                seen_dates[date_str] = bova_df
            else:
                print(f"    WARNING: No data returned for {date_str}")
                seen_dates[date_str] = pd.DataFrame()

        b3_day = seen_dates[date_str]
        if b3_day.empty:
            results.append({
                "validation_date": date_str,
                "rb3_type": row["rb3_type"],
                "rb3_strike": row["rb3_strike"],
                "b3_ticker": None,
                "b3_last_price": None,
                "b3_avg_price": None,
                "b3_min_price": None,
                "b3_max_price": None,
                "b3_trade_qty": None,
                "b3_found": False,
            })
            continue

        # Match by finding the option with strike closest to rb3's strike
        # B3 negotiation data doesn't directly expose strike — we need to join
        # with product data. For now, use a heuristic: the BOVA ticker whose
        # LastPrice is closest to rb3's mark.
        # A better approach joins via the IN (product) bulletin — see Step 3.
        results.append({
            "validation_date": date_str,
            "rb3_type": row["rb3_type"],
            "rb3_strike": row["rb3_strike"],
            "b3_day_data": b3_day,  # keep for Step 3 join
        })

    return results  # raw, will be processed in Step 3


def fetch_b3_product_info(targets_df: pd.DataFrame) -> dict:
    """
    For each unique validation date, download B3's product (IN) bulletin
    to get strike/expiry/style per ticker. Cache by date.
    Returns dict: date_str -> DataFrame with columns [Ticker, Style, Type, Strike, Maturity]
    """
    product_cache = {}
    for date_str in targets_df["validation_date"].unique():
        if date_str in product_cache:
            continue
        print(f"  Fetching B3 product info for {date_str}...")
        prod_df = get_b3_daily(date_str, type="product")
        if not prod_df.empty:
            bova_prod = prod_df[prod_df["Ticker"].str.startswith("BOVA", na=False)].copy()
            product_cache[date_str] = bova_prod
        else:
            product_cache[date_str] = pd.DataFrame()
    return product_cache


def match_b3_to_targets(targets_df: pd.DataFrame,
                         neg_cache: dict,
                         prod_cache: dict) -> pd.DataFrame:
    """
    For each row in targets_df, find the matching B3 contract using
    product data (strike + type + expiration), then retrieve its
    negotiation data (prices + volume).
    """
    rows = []

    for _, t in targets_df.iterrows():
        date_str = t["validation_date"]
        prod = prod_cache.get(date_str, pd.DataFrame())
        neg = neg_cache.get(date_str, pd.DataFrame())

        b3_last = None
        b3_avg = None
        b3_min = None
        b3_max = None
        b3_qty = None
        b3_ticker = None
        b3_style = None
        b3_found = False

        if not prod.empty and not neg.empty:
            # Convert B3 types: CALL/PUT
            b3_type_map = {"call": "CALL", "put": "PUT"}
            b3_type = b3_type_map.get(t["rb3_type"], t["rb3_type"].upper())

            # Match on type + strike (within 1%) + expiry (within 5 days)
            try:
                prod["Strike_f"] = prod["Strike"].astype(float)
                prod["Maturity_d"] = pd.to_datetime(prod["Maturity"])
                t_strike = float(t["rb3_strike"])
                t_expiry = pd.to_datetime(t["rb3_expiration"])

                mask = (
                    (prod["Type"] == b3_type) &
                    (prod["Strike_f"].between(t_strike * 0.99, t_strike * 1.01)) &
                    (prod["Maturity_d"].between(
                        t_expiry - pd.Timedelta(days=5),
                        t_expiry + pd.Timedelta(days=5)
                    ))
                )
                matched = prod[mask]

                if not matched.empty:
                    b3_ticker = matched.iloc[0]["Ticker"]
                    b3_style = matched.iloc[0].get("Style", "UNKNOWN")

                    # Look up in negotiation data
                    neg_row = neg[neg["Ticker"] == b3_ticker]
                    if not neg_row.empty:
                        neg_row = neg_row.iloc[0]
                        b3_last = float(neg_row["LastPrice"]) if neg_row["LastPrice"] else None
                        b3_avg = float(neg_row["AvgPrice"]) if neg_row["AvgPrice"] else None
                        b3_min = float(neg_row["MinPrice"]) if neg_row["MinPrice"] else None
                        b3_max = float(neg_row["MaxPrice"]) if neg_row["MaxPrice"] else None
                        b3_qty = int(float(neg_row["TradeQty"])) if neg_row["TradeQty"] else None
                        b3_found = True
            except Exception as e:
                print(f"    Match error for {date_str} {t['rb3_type']} strike={t['rb3_strike']}: {e}")

        rows.append({
            "validation_date": date_str,
            "rb3_date": t["rb3_date"],
            "rb3_type": t["rb3_type"],
            "rb3_strike": t["rb3_strike"],
            "rb3_expiration": t["rb3_expiration"],
            "rb3_mark": t["rb3_mark"],
            "rb3_bid": t["rb3_bid"],
            "rb3_ask": t["rb3_ask"],
            "rb3_volume": t["rb3_volume"],
            "rb3_delta": t["rb3_delta"],
            "rb3_iv": t["rb3_iv"],
            "b3_ticker": b3_ticker,
            "b3_style": b3_style,
            "b3_last_price": b3_last,
            "b3_avg_price": b3_avg,
            "b3_min_price": b3_min,
            "b3_max_price": b3_max,
            "b3_trade_qty": b3_qty,
            "b3_found": b3_found,
        })

    return pd.DataFrame(rows)


# ─────────────────────────────────────────────
# Step 3: Compute validation metrics
# ─────────────────────────────────────────────

def compute_metrics(comparison: pd.DataFrame) -> dict:
    """
    Compute three validation metrics:
    - mark_vs_last:    rb3_mark vs b3_last_price (±10% tolerance)
    - mark_vs_avg:     rb3_mark vs b3_avg_price  (±10% tolerance)
    - volume_match:    rb3_volume vs b3_trade_qty (±50% tolerance — volume noisier)
    - bid_range_check: is rb3_bid within [b3_min, b3_last]? (feasibility check)
    - ask_range_check: is rb3_ask >= b3_last? (feasibility check)
    """
    valid = comparison[comparison["b3_found"]].copy()

    metrics = {
        "total_targets": len(comparison),
        "b3_found": comparison["b3_found"].sum(),
        "b3_found_pct": comparison["b3_found"].mean() * 100,
    }

    if valid.empty:
        metrics["verdict"] = "INSUFFICIENT_DATA"
        return metrics

    # Mark vs LastPrice
    has_last = valid["b3_last_price"].notna() & (valid["b3_last_price"] > 0)
    if has_last.sum() > 0:
        v = valid[has_last]
        diff_pct = (v["rb3_mark"] - v["b3_last_price"]).abs() / v["b3_last_price"]
        metrics["mark_vs_last_match_pct"] = (diff_pct < 0.10).mean() * 100
        metrics["mark_vs_last_median_diff_pct"] = diff_pct.median() * 100
        metrics["mark_vs_last_n"] = len(v)
    else:
        metrics["mark_vs_last_match_pct"] = None

    # Mark vs AvgPrice
    has_avg = valid["b3_avg_price"].notna() & (valid["b3_avg_price"] > 0)
    if has_avg.sum() > 0:
        v = valid[has_avg]
        diff_pct = (v["rb3_mark"] - v["b3_avg_price"]).abs() / v["b3_avg_price"]
        metrics["mark_vs_avg_match_pct"] = (diff_pct < 0.10).mean() * 100
        metrics["mark_vs_avg_median_diff_pct"] = diff_pct.median() * 100

    # Volume match (±50%)
    has_vol = valid["b3_trade_qty"].notna() & (valid["b3_trade_qty"] > 0) & valid["rb3_volume"].notna()
    if has_vol.sum() > 0:
        v = valid[has_vol]
        vol_ratio = v["rb3_volume"] / v["b3_trade_qty"]
        metrics["volume_ratio_median"] = vol_ratio.median()
        metrics["volume_within_50pct"] = (vol_ratio.between(0.5, 2.0)).mean() * 100

    # Bid feasibility: rb3_bid should be <= b3_last_price (you can't sell above last)
    has_bid = valid["rb3_bid"].notna() & (valid["rb3_bid"] > 0) & has_last
    if has_bid.sum() > 0:
        v = valid[has_bid]
        metrics["bid_below_last_pct"] = (v["rb3_bid"] <= v["b3_last_price"] * 1.05).mean() * 100

    # Ask feasibility: rb3_ask should be >= b3_last_price (can't buy below last)
    has_ask = valid["rb3_ask"].notna() & (valid["rb3_ask"] > 0) & has_last
    if has_ask.sum() > 0:
        v = valid[has_ask]
        metrics["ask_above_last_pct"] = (v["rb3_ask"] >= v["b3_last_price"] * 0.95).mean() * 100

    # Spread analysis (how wide is rb3's implied spread?)
    has_both = (valid["rb3_bid"] > 0) & (valid["rb3_ask"] > 0) & (valid["rb3_mark"] > 0)
    if has_both.sum() > 0:
        v = valid[has_both]
        spread_pct = (v["rb3_ask"] - v["rb3_bid"]) / v["rb3_mark"]
        metrics["rb3_spread_median_pct"] = spread_pct.median() * 100
        metrics["rb3_spread_mean_pct"] = spread_pct.mean() * 100
        metrics["rb3_spread_p75_pct"] = spread_pct.quantile(0.75) * 100

    # Verdict
    mark_match = metrics.get("mark_vs_last_match_pct", 0) or 0
    if mark_match >= 80:
        metrics["verdict"] = "PASS"
    elif mark_match >= 50:
        metrics["verdict"] = "PARTIAL"
    else:
        metrics["verdict"] = "FAIL"

    return metrics


# ─────────────────────────────────────────────
# Step 4: Extract BOVA11 option exercise style
# ─────────────────────────────────────────────

def extract_bova11_style(prod_cache: dict) -> str:
    """
    Extract the official B3 exercise style for BOVA11 options
    (European = EURO, American = AMER).
    Uses the most recent date with product data.
    """
    for date_str in sorted(prod_cache.keys(), reverse=True):
        prod = prod_cache[date_str]
        if prod.empty:
            continue
        bova = prod[prod["Ticker"].str.startswith("BOVA")]
        if bova.empty:
            continue
        styles = bova["Style"].dropna().unique()
        if len(styles) > 0:
            return f"Date: {date_str}, Styles found: {styles.tolist()}"
    return "Could not determine — no product data available"


# ─────────────────────────────────────────────
# Step 5: Write the report
# ─────────────────────────────────────────────

def write_report(comparison: pd.DataFrame, metrics: dict, style_info: str):
    today = datetime.now().strftime("%Y-%m-%d")
    report_path = f"docs/{today} - rb3 price validation.md"

    with open(report_path, "w") as f:
        f.write(f"# rb3 Price Validation Against B3 Official Bulletin\n\n")
        f.write(f"**Date completed:** {today}\n")
        f.write(f"**Method:** Automated — B3 official daily bulletin API\n")
        f.write(f"**Source:** `scripts/validate_b3_prices.py`\n\n")
        f.write("---\n\n")

        f.write("## Summary\n\n")
        f.write(f"| Metric | Value |\n|--------|-------|\n")
        f.write(f"| Validation dates | {metrics['total_targets'] // 2} |\n")
        f.write(f"| Target contracts | {metrics['total_targets']} |\n")
        f.write(f"| B3 contract matched | {metrics['b3_found']} ({metrics['b3_found_pct']:.0f}%) |\n")
        if metrics.get("mark_vs_last_match_pct") is not None:
            f.write(f"| rb3_mark vs B3 LastPrice (±10%) | {metrics['mark_vs_last_match_pct']:.0f}% |\n")
            f.write(f"| Median mark diff | {metrics.get('mark_vs_last_median_diff_pct', 'N/A'):.1f}% |\n")
        if metrics.get("rb3_spread_median_pct") is not None:
            f.write(f"| rb3 implied spread (median) | {metrics['rb3_spread_median_pct']:.1f}% of mark |\n")
            f.write(f"| rb3 implied spread (75th pct) | {metrics['rb3_spread_p75_pct']:.1f}% of mark |\n")
        if metrics.get("bid_below_last_pct") is not None:
            f.write(f"| rb3 bid ≤ B3 last (feasibility) | {metrics['bid_below_last_pct']:.0f}% |\n")
        if metrics.get("ask_above_last_pct") is not None:
            f.write(f"| rb3 ask ≥ B3 last (feasibility) | {metrics['ask_above_last_pct']:.0f}% |\n")
        f.write(f"\n**Verdict: {metrics['verdict']}**\n\n")

        f.write("---\n\n")
        f.write("## BOVA11 Option Exercise Style\n\n")
        f.write(f"{style_info}\n\n")
        f.write("Expected: `EURO` (European cash-settled) for BOVA11 ETF options.\n\n")

        f.write("---\n\n")
        f.write("## Detailed Comparison\n\n")
        cols = [
            "validation_date", "rb3_type", "rb3_strike", "rb3_expiration",
            "rb3_mark", "rb3_bid", "rb3_ask", "rb3_volume",
            "b3_ticker", "b3_last_price", "b3_avg_price", "b3_trade_qty",
            "b3_style", "b3_found"
        ]
        available = [c for c in cols if c in comparison.columns]
        f.write(comparison[available].to_markdown(index=False))
        f.write("\n\n")

        f.write("---\n\n")
        f.write("## Interpretation\n\n")
        verdict = metrics["verdict"]
        if verdict == "PASS":
            f.write(
                "rb3 mark prices match B3's official last-traded prices. "
                "The rb3 database is sourcing real B3 market data. "
                "V4 conclusions about mid-price execution modes are reliable. "
                "The bid/ask spread widths in rb3 represent real market conditions.\n"
            )
        elif verdict == "PARTIAL":
            f.write(
                "rb3 mark prices partially match B3 official data. "
                "Some discrepancies exist — possibly different settlement times or "
                "data vendors. V4 mid-price conclusions should be treated with caution. "
                "Consider running v4 with wider tolerance analysis.\n"
            )
        elif verdict == "FAIL":
            f.write(
                "**CRITICAL:** rb3 mark prices do NOT match B3 official data. "
                "The rb3 database may contain computed/synthetic prices rather than "
                "real market quotes. STOP — do not proceed with v4 until this is investigated.\n"
            )
        else:
            f.write(
                "Insufficient data to make a determination. "
                "Fewer than 5 contracts were matched. Try extending the date range "
                "or checking B3 server availability.\n"
            )

    print(f"\nReport written to: {report_path}")
    return report_path


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

def main():
    print("=" * 60)
    print("rb3 Price Validation Against B3 Official Bulletin")
    print("=" * 60)

    print("\nStep 1: Querying rb3 database for validation targets...")
    targets = get_rb3_targets(DB_PATH, VALIDATION_DATES)
    if targets.empty:
        print("ERROR: No targets found in rb3 DB. Check DB_PATH and date range.")
        sys.exit(1)
    print(f"  Found {len(targets)} target contracts across {len(VALIDATION_DATES)} dates")
    targets.to_csv(OUTPUT_DIR / "validation_targets.csv", index=False)
    print(f"  Saved: output/validation/validation_targets.csv")

    print("\nStep 2: Fetching B3 official bulletin data...")
    print("  (This downloads ~200KB per date × 10 dates × 2 types = ~4MB total)")

    neg_cache = {}
    prod_cache = {}
    for date_str in targets["validation_date"].unique():
        print(f"  [{date_str}] downloading negotiation data...")
        neg_df = get_b3_daily(date_str, type="negotiation")
        if not neg_df.empty:
            neg_cache[date_str] = neg_df[neg_df["Ticker"].str.startswith("BOVA", na=False)]
        else:
            neg_cache[date_str] = pd.DataFrame()

        print(f"  [{date_str}] downloading product data...")
        prod_df = get_b3_daily(date_str, type="product")
        if not prod_df.empty:
            prod_cache[date_str] = prod_df[prod_df["Ticker"].str.startswith("BOVA", na=False)]
        else:
            prod_cache[date_str] = pd.DataFrame()

        # Be polite to B3's server
        import time; time.sleep(0.5)

    print("\nStep 3: Matching B3 contracts to rb3 targets...")
    comparison = match_b3_to_targets(targets, neg_cache, prod_cache)
    comparison.to_csv(OUTPUT_DIR / "validation_comparison.csv", index=False)
    print(f"  Matched {comparison['b3_found'].sum()} of {len(comparison)} targets")
    print(f"  Saved: output/validation/validation_comparison.csv")

    print("\nStep 4: Extracting BOVA11 exercise style...")
    style_info = extract_bova11_style(prod_cache)
    print(f"  {style_info}")

    print("\nStep 5: Computing validation metrics...")
    metrics = compute_metrics(comparison)

    print("\n" + "=" * 60)
    print("VALIDATION RESULTS")
    print("=" * 60)
    for k, v in metrics.items():
        if v is not None:
            print(f"  {k}: {v:.1f}" if isinstance(v, float) else f"  {k}: {v}")

    print(f"\n  *** VERDICT: {metrics['verdict']} ***\n")

    if metrics["verdict"] == "FAIL":
        print("  CRITICAL: rb3 prices do not match B3 official data.")
        print("  Do NOT proceed to v4 until this is investigated.")

    print("\nStep 6: Writing report...")
    report_path = write_report(comparison, metrics, style_info)

    return metrics["verdict"]


if __name__ == "__main__":
    verdict = main()
    sys.exit(0 if verdict in ("PASS", "PARTIAL") else 1)
```

### Step 1.3 — Run the validation

```bash
python scripts/validate_b3_prices.py
```

Expected output:
- `output/validation/validation_targets.csv`
- `output/validation/validation_comparison.csv`
- `docs/YYYY-MM-DD - rb3 price validation.md`

**If the script exits with code 1 (FAIL verdict), STOP and report the findings before proceeding to Part 2.**

---

## Part 2: V4 Execution Sensitivity Grid

**Only run this if Part 1 returns PASS or PARTIAL.**

### What you're building

An execution sensitivity analysis that re-runs the backtest with 5 different fill assumptions to find the break-even execution model.

### Step 2.1 — Add `execution_mode` and `tick_size` to params

**File: `src/straddle/params.py`**

Add to `PricingParams` TypedDict:
```python
execution_mode: str    # "bid_ask" | "mid_minus_1tick" | "mid" | "mid_plus_1tick" | "volume_filtered"
tick_size: float       # minimum price increment
volume_filter_min_pct: float  # for volume_filtered: skip entries with volume < this percentile
```

Add to `PRICING` defaults:
```python
"execution_mode": "bid_ask",
"tick_size": 0.05,
"volume_filter_min_pct": 0.50,
```

Add to `MARKET_PRESETS`:
```python
# spy:
"tick_size": 0.01,
# bova11:
"tick_size": 0.05,
# petr4:
"tick_size": 0.05,
```

### Step 2.2 — Modify `MarketEngine` for all 5 execution modes

**File: `src/straddle/engines.py`**

In `MarketEngine.__init__()`, add:
```python
self._exec_mode = params.get("execution_mode", "bid_ask")
self._tick_size = params.get("tick_size", 0.05)
self._volume_filter_min_pct = params.get("volume_filter_min_pct", 0.50)
self.uses_real_fills = self._exec_mode in ("bid_ask", "volume_filtered")

# Pre-compute volume threshold for volume_filtered mode
self._daily_vol_threshold = 0.0
if self._exec_mode == "volume_filtered":
    self._daily_vol_threshold = self._compute_volume_threshold()
```

Add `_compute_volume_threshold()` method:
```python
def _compute_volume_threshold(self) -> float:
    """Compute the daily volume percentile threshold for this underlying."""
    cur = self._conn.cursor()
    cur.execute(
        "SELECT volume FROM options_data WHERE underlying = ? AND volume > 0",
        (self._underlying,)
    )
    vols = sorted(r[0] for r in cur.fetchall() if r[0] is not None)
    if not vols:
        return 0.0
    idx = int(len(vols) * self._volume_filter_min_pct)
    return float(vols[min(idx, len(vols) - 1)])
```

Modify `get_entry_marks()` to dispatch on `execution_mode`:
```python
def get_entry_marks(self, ...):
    # ... existing DB lookup to get put_row, call_row ...

    exec_mode = self._exec_mode
    tick = self._tick_size

    if exec_mode == "bid_ask":
        put_price = float(put_row["bid"]) if float(put_row["bid"]) > 0 else None
        call_price = float(call_row["bid"]) if float(call_row["bid"]) > 0 else None
        if put_price is None or call_price is None:
            return None  # no valid bid, fall back to synthetic

    elif exec_mode == "volume_filtered":
        put_vol = float(put_row.get("volume") or 0)
        call_vol = float(call_row.get("volume") or 0)
        if put_vol < self._daily_vol_threshold or call_vol < self._daily_vol_threshold:
            return None  # skip this entry — low volume day
        put_price = float(put_row["mark"])
        call_price = float(call_row["mark"])

    elif exec_mode == "mid":
        put_price = float(put_row["mark"])
        call_price = float(call_row["mark"])

    elif exec_mode == "mid_minus_1tick":
        put_price = max(float(put_row["mark"]) - tick, 0.01)
        call_price = max(float(call_row["mark"]) - tick, 0.01)

    elif exec_mode == "mid_plus_1tick":
        put_price = float(put_row["mark"]) + tick
        call_price = float(call_row["mark"]) + tick

    else:
        put_price = float(put_row["mark"])
        call_price = float(call_row["mark"])

    return (float(put_row["strike"]), float(call_row["strike"]),
            put_price, call_price, True)
```

Modify `get_leg_mark_with_source()` and `_strike_close_price()` for consistency on close/MTM:
```python
# Closing side: mirror entry mode (worse fills at entry = worse fills at exit)
if exec_mode == "bid_ask":
    close_price = float(row["ask"])
elif exec_mode in ("volume_filtered", "mid"):
    close_price = float(row["mark"])
elif exec_mode == "mid_minus_1tick":
    close_price = float(row["mark"]) + tick  # buying back costs slightly more
elif exec_mode == "mid_plus_1tick":
    close_price = max(float(row["mark"]) - tick, 0.01)  # buying back slightly less
```

Note: For `volume_filtered`, exits always use mid-price (we don't skip exits based on volume — once in the trade, we exit regardless).

### Step 2.3 — Add `execution_mode` to grid search

**File: `scripts/grid_search.py`**

Add `execution_mode` to `GRID_DIMS`.

In `_apply_grid_overrides()`, add handling for `execution_mode`:
```python
elif key == "execution_mode":
    overrides["execution_mode"] = val
```

### Step 2.4 — Create the v4 grid search notebook

**File: `research/2026-05-14 - B3 - v4 execution sensitivity.ipynb`**

Grid configuration:
```python
GRID = {
    "target_delta": [0.16, 0.20, 0.25],
    "dte_max": [30, 45],
    "profit_target_pct": [0.50],
    "manage_at_dte": [7, 14],
    "vix_filter": ["OFF", "rv_pct:80"],
    "defensive_leg_roll": [False],
    "stop_loss_pct": [3.0],
    "execution_mode": ["bid_ask", "mid_minus_1tick", "mid", "mid_plus_1tick", "volume_filtered"],
}
# 3 × 2 × 1 × 2 × 2 × 1 × 1 × 5 = 120 combos × 2 periods = 240 backtests
```

Fixed settings (same as v3):
```python
mode = "market"
cash_investment_mode = "risk_free"
cash_yield_annual = 0
use_cdi_ivs = True
```

### Step 2.5 — Analysis cells to include in the notebook

The notebook must include all of the following:

**Cell A — Sharpe vs execution_mode boxplot (most important chart)**
One subplot per period (train / holdout). X-axis: execution_mode in order
`[bid_ask, mid_minus_1tick, mid, mid_plus_1tick, volume_filtered]`. Y-axis: Sharpe.
Add a horizontal line at y=0.

**Cell B — Break-even execution level**
Find the leftmost execution mode where holdout median Sharpe crosses zero (if any).
Print a one-line conclusion: `"Break-even: mid"` or `"No break-even — all modes negative"`.

**Cell C — Sharpe by execution_mode × target_delta**
Heatmap or grouped bar chart. Answers: does 16-delta have more execution sensitivity
than 25-delta?

**Cell D — Volume filter skip rate**
For `volume_filtered` mode: what % of monthly entries were skipped?
Print: `"Volume filter skipped X% of entries"`.
If >40%, note this means `volume_filtered` has far fewer trades and Sharpe is less stable.

**Cell E — Spread cost analysis**
From the comparison data, compute `(ask - bid) / mark` for all options in the DB
with `bid > 0 AND ask > 0`. Produce:
- Distribution by delta bucket (0.10–0.20, 0.20–0.30, 0.30–0.50)
- Distribution by year (2017, 2018, ..., 2025)
- Median spread as % of mark for the 16-delta bucket

This quantifies exactly how much the "sell at bid" assumption costs relative to mid.

**Cell F — Per-trade P&L comparison for one config**
Pick the config with the best holdout Sharpe overall. Show per-trade P&L for each
execution mode side-by-side (one row per trade, columns = execution modes).

**Cell G — Source tracking by execution mode**
For each execution mode, report `entry_db_pct` and `mtm_avg_db_pct`.
Are they the same across modes? (They should be, since `execution_mode` doesn't change
which entries succeed, just how they're priced — except for `volume_filtered` which
reduces the entry set.)

### Step 2.6 — Write tests

**File: `tests/test_execution_modes.py`**

Write at least 5 unit tests:
1. `test_bid_ask_uses_bid_to_sell`: entry price = bid for `bid_ask` mode
2. `test_mid_uses_mark`: entry price = mark for `mid` mode
3. `test_mid_minus_1tick_below_mid`: entry price = mark - tick for `mid_minus_1tick`
4. `test_mid_plus_1tick_above_mid`: entry price = mark + tick for `mid_plus_1tick`
5. `test_volume_filtered_skips_low_volume`: entry returns None when volume < threshold
6. `test_volume_filtered_accepts_high_volume`: entry proceeds when volume ≥ threshold

Use a mock DB with 3-5 rows to keep tests fast and isolated.

---

## What to report when done

Produce a document `docs/YYYY-MM-DD - v4 execution sensitivity results.md` containing:

1. **Part 1 verdict** (PASS / PARTIAL / FAIL) with key metrics
2. **BOVA11 option exercise style** as confirmed by B3's official product bulletin
3. **Break-even execution level** (the leftmost mode with positive holdout Sharpe, or "none")
4. **Spread cost measured from the data** (median spread % at 16-delta)
5. **Volume filter skip rate** for `volume_filtered` mode
6. **One-paragraph conclusion** addressing the central research question:
   "Does the BOVA11 short strangle VRP exist, and can a retail trader capture it?"

This conclusion must be one of:
   - **A:** "VRP exists and is capturable at mid or better execution (limit orders)."
   - **B:** "VRP exists but is fully consumed by bid-ask spread at current B3 liquidity levels."
   - **C:** "VRP does not appear to exist even at mid-price — strategy is structurally unviable."
   - **D:** "Insufficient data to conclude — see caveats." (only if Part 1 returns PARTIAL and coverage is <60%)

---

## Deviations allowed

- If the B3 server returns empty data for more than 3 of the 10 validation dates, skip
  those dates and proceed with whatever is available. Document which dates had no data.
- If `volume_filtered` skips >50% of entries for any config, also add `volume_filter_min_pct=0.25`
  as an additional grid dimension for that mode only. Document this deviation.
- If Part 1 returns PARTIAL (50–80% mark match rate), still run Part 2 but add a prominently
  visible caveat in the final report: "rb3 prices partially validated; bid_ask mode conclusions
  may be unreliable."

---

## Definition of done

- [ ] `scripts/b3_bulletin_fetcher.py` — B3 bulletin fetcher (from GitHub source)
- [ ] `scripts/validate_b3_prices.py` — validation script (comparison + verdict)
- [ ] `output/validation/validation_targets.csv` — rb3 data for 20 contracts
- [ ] `output/validation/validation_comparison.csv` — side-by-side comparison
- [ ] `docs/YYYY-MM-DD - rb3 price validation.md` — Part 1 report with PASS/PARTIAL/FAIL
- [ ] `src/straddle/params.py` — execution_mode, tick_size, volume_filter_min_pct added
- [ ] `src/straddle/engines.py` — MarketEngine handles all 5 execution modes + volume filter
- [ ] `tests/test_execution_modes.py` — 6 unit tests, all passing
- [ ] `research/2026-05-14 - B3 - v4 execution sensitivity.ipynb` — 7 analysis cells
- [ ] `data/B3/v4_grid_search_results.parquet` — 240-row grid output
- [ ] `docs/YYYY-MM-DD - v4 execution sensitivity results.md` — final report with A/B/C/D conclusion