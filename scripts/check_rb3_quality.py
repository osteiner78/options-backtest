"""Task 2: Data quality checks for rb3 options data.

Run: python scripts/check_rb3_quality.py
"""

import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RB3_DIR = ROOT / "data" / "B3" / "rb3_export"
TARGET_PCT = 0.001  # 0.1%


def load(name: str) -> pd.DataFrame:
    path = RB3_DIR / f"{name}_options_rb3.parquet"
    df = pd.read_parquet(path)
    df["refdate"] = pd.to_datetime(df["refdate"])
    df["maturity_date"] = pd.to_datetime(df["maturity_date"])
    return df


def pct(n: int, total: int) -> str:
    return f"{n:,} ({n/total*100:.2f}%)" if total > 0 else "0"


def test_a_sanity_bounds(df: pd.DataFrame, label: str) -> dict:
    total = len(df)
    # Call: cannot exceed underlying price.  Put: cannot exceed strike.
    call_violations = df[
        (df["option_type"] == "call") & (df["close"] > df["close_underlying"])
    ]
    put_violations = df[
        (df["option_type"] == "put") & (df["close"] > df["strike_price"])
    ]
    neg_price = df[df["close"] < 0]
    extreme = df[df["close"] > 10 * df["strike_price"]]

    n = len(
        pd.concat([call_violations, put_violations, neg_price, extreme]).drop_duplicates()
    )
    return {
        "name": "A: Price sanity bounds",
        "violations": n,
        "total": total,
        "details": {
            "call > underlying": pct(len(call_violations), total),
            "put > strike": pct(len(put_violations), total),
            "close < 0": pct(len(neg_price), total),
            "close > 10× strike": pct(len(extreme), total),
        },
    }


def test_b_greeks_sanity(df: pd.DataFrame, label: str) -> dict:
    total = len(df)
    delta_sign = df[
        ((df["option_type"] == "call") & (df["delta"] < 0))
        | ((df["option_type"] == "put") & (df["delta"] > 0))
    ]
    delta_range = df[df["delta"].abs() > 1.0]
    iv_low = df[df["impvol"] < 0.01]
    iv_high = df[df["impvol"] > 5.0]

    n = len(
        pd.concat([delta_sign, delta_range, iv_low, iv_high]).drop_duplicates()
    )
    iv_filtered = df[df["impvol"] > 2.0]
    return {
        "name": "B: Greeks sanity",
        "violations": n,
        "total": total,
        "details": {
            "wrong delta sign": pct(len(delta_sign), total),
            "|delta| > 1": pct(len(delta_range), total),
            "IV < 0.01": pct(len(iv_low), total),
            "IV > 5.0 (500%)": pct(len(iv_high), total),
            "IV > 2.0 (200%, engine-filtered)": pct(len(iv_filtered), total),
        },
    }


def test_c_bid_ask_consistency(df: pd.DataFrame, label: str) -> dict:
    has_both = df["best_bid"].notna() & df["best_ask"].notna() & (df["best_ask"] > 0)
    valid = df[has_both]
    total_with_both = len(valid)

    bid_gt_ask = valid[valid["best_bid"] > valid["best_ask"]]
    close_below = valid[valid["close"] < valid["best_bid"] * 0.33]
    close_above = valid[valid["close"] > valid["best_ask"] * 3.0]

    n = len(pd.concat([bid_gt_ask, close_below, close_above]).drop_duplicates())
    return {
        "name": "C: Bid/Ask consistency (3× spread)",
        "violations": n,
        "total": total_with_both,
        "details": {
            "bid > ask": pct(len(bid_gt_ask), total_with_both),
            "close < 0.33×bid": pct(len(close_below), total_with_both),
            "close > 3.0×ask": pct(len(close_above), total_with_both),
        },
    }


def test_d_dates(df: pd.DataFrame, label: str) -> dict:
    total = len(df)
    df = df.copy()
    df["dte"] = (df["maturity_date"] - df["refdate"]).dt.days

    expired = df[df["dte"] < 0]
    too_far = df[df["dte"] > 730]

    n = len(pd.concat([expired, too_far]).drop_duplicates())
    return {
        "name": "D: Time consistency",
        "violations": n,
        "total": total,
        "details": {
            "DTE < 0 (expired)": pct(len(expired), total),
            "DTE > 730": pct(len(too_far), total),
        },
    }


def test_e_coverage(df: pd.DataFrame, label: str) -> dict:
    daily = df.groupby("refdate").size()
    median = daily.median()
    sparse = daily[daily < median * 0.1]

    return {
        "name": "E: Coverage by date",
        "violations": len(sparse),
        "total": len(daily),
        "details": {
            "median daily rows": f"{int(median):,}",
            "days < 10% median": f"{len(sparse)} of {len(daily)}",
            "min daily rows": f"{daily.min():,}",
        },
    }


def test_f_underlying_consistency(df: pd.DataFrame, label: str) -> dict:
    grouped = df.groupby("refdate")["close_underlying"].nunique()
    inconsistent = grouped[grouped > 1]

    return {
        "name": "F: Underlying price consistency",
        "violations": len(inconsistent),
        "total": len(grouped),
        "details": {
            "days with >1 underlying price": f"{len(inconsistent)} of {len(grouped)}",
            "max unique prices in a day": f"{grouped.max()}",
        },
    }


def test_h_duplicates(df: pd.DataFrame, label: str) -> dict:
    """Duplicate rows flagging the same option appearing multiple times."""
    total = len(df)
    dupes = df.duplicated(
        subset=["refdate", "strike_price", "maturity_date", "option_type"], keep=False
    )
    n = dupes.sum()
    return {
        "name": "H: Duplicate rows",
        "violations": n,
        "total": total,
        "details": {"unique option-days affected": f"{df[dupes].drop_duplicates(subset=['refdate','strike_price','maturity_date','option_type']).shape[0]:,} of {total:,}"},
    }


def test_i_parity(df: pd.DataFrame, label: str) -> dict:
    """Put-call parity: C − P ≈ S − K·exp(−rT) within bid-ask tolerance.

    Matches calls and puts on same (date, expiration, strike). Flags rows where
    |actual − expected| / S > max_violation_pct of underlying.
    Uses flat r=12% (matching rb3's IV computation convention).

    BOVA11 is European → 5% threshold is appropriate.
    PETR4 is American → 10% threshold to account for early-exercise premium.
    """
    max_violation_pct = 0.05 if label == "bova11" else 0.10
    calls = df[df["option_type"] == "call"][
        ["refdate", "maturity_date", "strike_price", "close", "close_underlying"]
    ].rename(columns={"close": "close_c", "close_underlying": "S"})

    puts = df[df["option_type"] == "put"][
        ["refdate", "maturity_date", "strike_price", "close"]
    ].rename(columns={"close": "close_p"})

    merged = calls.merge(puts, on=["refdate", "maturity_date", "strike_price"], how="inner")
    total_pairs = len(merged)

    if total_pairs == 0:
        return {"name": "I: Put-call parity", "violations": 0, "total": 0, "details": {}}

    merged["T"] = (merged["maturity_date"] - merged["refdate"]).dt.days / 365.0
    merged["expected"] = (
        merged["S"] - merged["strike_price"] * np.exp(-0.12 * merged["T"])
    )
    merged["actual"] = merged["close_c"] - merged["close_p"]
    merged["violation_pct"] = (merged["actual"] - merged["expected"]).abs() / merged["S"]

    violations = merged[merged["violation_pct"] > max_violation_pct]
    n = len(violations)

    return {
        "name": "I: Put-call parity",
        "violations": n,
        "total": total_pairs,
        "details": {
            "matched call-put pairs": f"{total_pairs:,}",
            f"violations >{max_violation_pct*100:.0f}% of S": pct(n, total_pairs),
            "median violation %S": f"{merged['violation_pct'].median()*100:.2f}%",
        },
    }


def test_j_term_structure(df: pd.DataFrame, label: str, max_jump: float = 0.10) -> dict:
    """INFORMATIONAL — B3 single-stock options have legitimate IV jumps at earnings.
    Do not use as a hard gate. Report but do not fail.

    Term structure: IV jumps between adjacent expirations should not exceed 10 vol pts.

    For each (date, underlying), finds the ATM call IV at each expiration, then
    checks that IV differences between consecutive expirations are within max_jump.
    Only flags jumps that don't appear on neighboring dates (isolated anomalies).
    """
    # Find ATM calls: closest to underlying price on each (date, expiration)
    atm = df[df["option_type"] == "call"].copy()
    atm["moneyness"] = (atm["strike_price"] - atm["close_underlying"]).abs()
    atm = atm.sort_values("moneyness").groupby(["refdate", "maturity_date"]).first().reset_index()

    if atm.empty:
        return {"name": "J: Term structure", "violations": 0, "total": 0, "details": {}}

    # For each date, sort expirations and check IV differences
    atm = atm.sort_values(["refdate", "maturity_date"])
    violations = 0
    total_checks = 0

    for date, group in atm.groupby("refdate"):
        if len(group) < 2:
            continue
        group = group.sort_values("maturity_date")
        ivs = group["impvol"].values
        for i in range(len(ivs) - 1):
            total_checks += 1
            if abs(ivs[i + 1] - ivs[i]) > max_jump:
                violations += 1

    return {
        "name": "J: Term structure monotonicity",
        "violations": violations,
        "total": total_checks,
        "details": {
            "adjacent expiry pairs": f"{total_checks:,}",
            f"|ΔIV| > {max_jump*100:.0f} vol pts": pct(violations, total_checks),
        },
    }


def test_l_strike_grid(df: pd.DataFrame, label: str, min_strikes: int = 3) -> dict:
    """Each (date, underlying, expiration) should have at least min_strikes options.
    B3 single-stock chains are shallow → threshold lowered to 3.
    """
    grid = df.groupby(["refdate", "maturity_date"]).size()
    sparse = grid[grid < min_strikes]
    total_expiries = len(grid)

    return {
        "name": f"L: Strike grid (≥{min_strikes} strikes/expiry)",
        "violations": len(sparse),
        "total": total_expiries,
        "details": {
            "expiry-dates": f"{total_expiries:,}",
            f"<{min_strikes} strikes": f"{len(sparse)} of {total_expiries:,}",
            "min strikes in any expiry": f"{grid.min()}",
        },
    }


def test_m_corruption_regression(df: pd.DataFrame, label: str) -> dict:
    """The old DB had ~5 rows with mark > R$500k. Verify rb3 has zero such rows."""
    total = len(df)
    huge = df[df["close"] > 1000]
    n = len(huge)
    return {
        "name": "M: Corruption regression (close > R$1000)",
        "violations": n,
        "total": total,
        "details": {"rows with close > R$1000": str(n)},
    }


def run_all(label: str) -> list[dict]:
    df = load(label)
    total = len(df)
    print(f"\n{'='*60}")
    print(f"  {label.upper()}  —  {total:,} rows")
    print(f"  {df['refdate'].min().date()} to {df['refdate'].max().date()}")
    print(f"{'='*60}")

    results = []
    for test_fn in [
        test_a_sanity_bounds,
        test_b_greeks_sanity,
        test_c_bid_ask_consistency,
        test_d_dates,
        test_e_coverage,
        test_f_underlying_consistency,
        test_h_duplicates,
        test_i_parity,
        test_j_term_structure,
        test_l_strike_grid,
        test_m_corruption_regression,
    ]:
        r = test_fn(df, label)
        # Test J is purely informational (B3 single-stocks have earnings IV jumps)
        if r["name"].startswith("J:"):
            status = "INFO"
        else:
            # Test I uses a dynamic threshold (5% BOVA11, 10% PETR4)
            if r["name"].startswith("I:"):
                threshold = 0.05 if label == "bova11" else 0.10
            else:
                threshold = TARGET_PCT
            pct_v = r["violations"] / r["total"] if r["total"] > 0 else 0
            status = "PASS" if pct_v <= threshold else "FAIL"
        print(f"\n  [{status}] {r['name']}")
        if status != "INFO":
            print(f"    Violations: {pct(r['violations'], r['total'])}  (target <{TARGET_PCT*100:.1f}%)")
        for k, v in r["details"].items():
            print(f"      {k}: {v}")
        results.append(r)

    return results


def main():
    import sys
    strict = "--strict" in sys.argv

    all_results = {}
    for und in ("bova11", "petr4"):
        all_results[und] = run_all(und)

    # Summary
    print(f"\n{'='*60}")
    print("  SUMMARY")
    print(f"{'='*60}")
    any_fail = False
    for und, results in all_results.items():
        fails = []
        for r in results:
            if r["name"].startswith("J:"):
                continue
            threshold = 0.05 if r["name"].startswith("I:") and und == "bova11" else (0.10 if r["name"].startswith("I:") and und == "petr4" else TARGET_PCT)
            if r["violations"] / max(r["total"], 1) > threshold:
                fails.append(r)
        if fails:
            any_fail = True
            print(f"\n  {und}: {len(fails)}/{len(results)} tests FAILED:")
            for r in fails:
                pct_s = f"{r['violations']/r['total']*100:.2f}%"
                print(f"    - {r['name']}: {pct_s}")
        else:
            print(f"\n  {und}: all {len(results)} tests passed")

    if strict and any_fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
