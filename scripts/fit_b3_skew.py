"""Fit put_slope and call_slope from B3 options data.

The SyntheticEngine skew model:
    put_vol  = atm_vol * (1 + put_slope  * (0.50 - |delta|))
    call_vol = atm_vol * (1 - call_slope * (0.50 - |delta|))

This script fits put_slope and call_slope from the empirical IV smile in
data/B3/b3_options.db using volume-weighted OLS, then prints the values
ready to paste into MARKET_PRESETS in params.py.

Produces diagnostic plots saved to data/B3/skew_fit_*.png.

Usage:
    python scripts/fit_b3_skew.py
    python scripts/fit_b3_skew.py --min-year 2017   # skip thin early data
    python scripts/fit_b3_skew.py --no-plot
"""

import argparse
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import matplotlib.pyplot as plt
    import matplotlib.gridspec as gridspec
    HAS_PLT = True
except ImportError:
    HAS_PLT = False


DB_PATH   = Path("data/B3/b3_options_rb3.db")
OUT_DIR   = Path("data/B3")

# ── Model constants ──────────────────────────────────────────────────────────

# ATM band: options whose |delta| falls here define the ATM vol reference
ATM_DELTA_LO = 0.42
ATM_DELTA_HI = 0.58

# OTM fitting band: options used to estimate the slope
OTM_DELTA_LO = 0.05   # exclude very deep OTM (noisy)
OTM_DELTA_HI = 0.38   # exclude near-ATM (distance ≈ 0, noisy slope estimate)

DTE_MIN = 20
DTE_MAX = 60


# ── Data loading ─────────────────────────────────────────────────────────────

def load_chain(underlying: str, min_year: int = 0) -> pd.DataFrame:
    """Load full option chain with valid delta and IV from the B3 SQLite."""
    con = sqlite3.connect(str(DB_PATH))
    df = pd.read_sql_query(
        """
        SELECT date, expiration, type, strike, volume,
               delta_cdi AS delta, implied_volatility_cdi AS iv
        FROM options_data
        WHERE underlying = ?
          AND delta_cdi IS NOT NULL
          AND implied_volatility_cdi IS NOT NULL
          AND implied_volatility_cdi < 2.0
          AND volume > 0
          AND bid > 0
          AND ask >= bid
        """,
        con,
        params=(underlying,),
        parse_dates=["date", "expiration"],
    )
    con.close()

    # DTE filter
    df["dte"] = (df["expiration"] - df["date"]).dt.days
    df = df[(df["dte"] >= DTE_MIN) & (df["dte"] <= DTE_MAX)]

    # Year filter
    if min_year:
        df = df[df["date"].dt.year >= min_year]

    df["abs_delta"] = df["delta"].abs()
    return df.reset_index(drop=True)


# ── ATM IV reference ─────────────────────────────────────────────────────────

def compute_atm_iv(df: pd.DataFrame) -> pd.DataFrame:
    """For each (date, expiration) slice, compute volume-weighted ATM IV.

    Returns df with an added `atm_iv` column.
    """
    atm = df[df["abs_delta"].between(ATM_DELTA_LO, ATM_DELTA_HI)].copy()
    if atm.empty:
        df["atm_iv"] = np.nan
        return df

    def wavg_iv(g):
        w = g["volume"].clip(lower=1)
        return np.average(g["iv"], weights=w)

    atm_ref = atm.groupby(["date", "expiration"]).apply(wavg_iv).rename("atm_iv")
    # Require at least 2 ATM options per slice for a reliable reference
    atm_count = atm.groupby(["date", "expiration"]).size().rename("atm_n")
    atm_ref = atm_ref[atm_count >= 2]

    df = df.merge(atm_ref, on=["date", "expiration"], how="inner")
    return df


# ── Slope computation ─────────────────────────────────────────────────────────

def compute_slopes(df: pd.DataFrame) -> tuple[float, float, pd.DataFrame]:
    """Fit put_slope and call_slope from normalised IV smile.

    For puts:  (iv / atm_iv - 1) = put_slope * distance   →  OLS without intercept
    For calls: (1 - iv / atm_iv) = call_slope * distance  →  OLS without intercept

    Returns (put_slope, call_slope, diagnostics_df).
    """
    df = df.copy()
    df["distance"] = 0.50 - df["abs_delta"]

    # OTM filter — exclude near-ATM and very deep OTM
    otm = df[df["abs_delta"].between(OTM_DELTA_LO, OTM_DELTA_HI)].copy()
    otm = otm[otm["atm_iv"] > 0.01]  # sanity: non-zero ATM IV
    otm["iv_ratio"] = otm["iv"] / otm["atm_iv"]

    # Clip extreme IV ratios (data artefacts from stale/illiquid quotes)
    otm = otm[otm["iv_ratio"].between(0.5, 3.0)]

    puts  = otm[otm["type"] == "put"]
    calls = otm[otm["type"] == "call"]

    def ols_slope(subset, target_col):
        """Volume-weighted OLS of target_col on distance (no intercept)."""
        x = subset["distance"].values
        y = subset[target_col].values
        w = subset["volume"].clip(lower=1).values
        # Weighted OLS: slope = Σ(w*x*y) / Σ(w*x²)
        return float(np.sum(w * x * y) / np.sum(w * x**2))

    puts["y"]  = puts["iv_ratio"] - 1.0           # model: put_slope * distance
    calls["y"] = 1.0 - calls["iv_ratio"]           # model: call_slope * distance

    put_slope  = ols_slope(puts,  "y") if len(puts)  > 100 else np.nan
    call_slope = ols_slope(calls, "y") if len(calls) > 100 else np.nan

    # Clip to physically sensible range
    put_slope  = float(np.clip(put_slope,  0.0, 1.5))
    call_slope = float(np.clip(call_slope, -0.5, 0.8))

    diag = pd.concat([puts.assign(leg="put"), calls.assign(leg="call")])
    return put_slope, call_slope, diag


# ── Stability over time ───────────────────────────────────────────────────────

def annual_slopes(df: pd.DataFrame) -> pd.DataFrame:
    """Compute fitted slopes per year to assess temporal stability."""
    rows = []
    for yr, grp in df.groupby(df["date"].dt.year):
        if len(grp) < 500:
            continue
        # Drop atm_iv if already present from the outer fit (merge would create _x/_y)
        grp = grp.drop(columns=["atm_iv"], errors="ignore")
        grp_atm = compute_atm_iv(grp)
        if "atm_iv" not in grp_atm.columns or grp_atm.empty:
            continue
        ps, cs, _ = compute_slopes(grp_atm)
        rows.append({"year": yr, "put_slope": ps, "call_slope": cs, "n": len(grp)})
    return pd.DataFrame(rows)


# ── Diagnostics plots ─────────────────────────────────────────────────────────

def plot_diagnostics(diag: pd.DataFrame, put_slope: float, call_slope: float,
                     label: str, out_path: Path) -> None:
    if not HAS_PLT:
        return
    fig = plt.figure(figsize=(14, 10))
    fig.suptitle(f"{label} — IV smile fit  "
                 f"(put_slope={put_slope:.3f}, call_slope={call_slope:.3f})", fontsize=13)
    gs = gridspec.GridSpec(2, 2, figure=fig)

    d_range = np.linspace(0, 0.45, 100)

    # ── Put smile ────────────────────────────────────────────────────────────
    ax = fig.add_subplot(gs[0, 0])
    puts = diag[diag["leg"] == "put"]
    ax.hexbin(puts["distance"], puts["iv_ratio"], gridsize=40, cmap="Blues",
              mincnt=1, linewidths=0.2)
    ax.plot(d_range, 1 + put_slope * d_range, "r-", lw=2,
            label=f"fit: slope={put_slope:.3f}")
    ax.axhline(1.0, ls="--", color="gray", lw=0.8)
    ax.set_xlabel("distance from ATM (0.50 − |δ|)")
    ax.set_ylabel("IV / ATM IV")
    ax.set_title("Put smile")
    ax.legend()

    # ── Call smile ───────────────────────────────────────────────────────────
    ax = fig.add_subplot(gs[0, 1])
    calls = diag[diag["leg"] == "call"]
    ax.hexbin(calls["distance"], calls["iv_ratio"], gridsize=40, cmap="Oranges",
              mincnt=1, linewidths=0.2)
    ax.plot(d_range, 1 - call_slope * d_range, "r-", lw=2,
            label=f"fit: slope={call_slope:.3f}")
    ax.axhline(1.0, ls="--", color="gray", lw=0.8)
    ax.set_xlabel("distance from ATM (0.50 − |δ|)")
    ax.set_ylabel("IV / ATM IV")
    ax.set_title("Call smile")
    ax.legend()

    # ── Residuals ─────────────────────────────────────────────────────────────
    ax = fig.add_subplot(gs[1, 0])
    puts["resid"] = (puts["iv_ratio"] - 1) - put_slope * puts["distance"]
    calls["resid"] = (1 - calls["iv_ratio"]) - call_slope * calls["distance"]
    ax.hist(puts["resid"].clip(-0.5, 0.5),  bins=60, alpha=0.6, color="steelblue",  label="puts")
    ax.hist(calls["resid"].clip(-0.5, 0.5), bins=60, alpha=0.6, color="darkorange", label="calls")
    ax.axvline(0, ls="--", color="gray", lw=0.8)
    ax.set_xlabel("residual (observed − model)")
    ax.set_title("Residuals")
    ax.legend()

    # ── IV at 16Δ comparison ─────────────────────────────────────────────────
    ax = fig.add_subplot(gs[1, 1])
    target_distance = 0.50 - 0.16  # 0.34
    put_mult  = 1 + put_slope  * target_distance
    call_mult = 1 - call_slope * target_distance
    spy_put   = 1 + 0.30 * target_distance
    spy_call  = 1 - 0.10 * target_distance
    bars = ax.bar(["put\n(fitted)", "call\n(fitted)", "put\n(SPY)", "call\n(SPY)"],
                  [put_mult, call_mult, spy_put, spy_call],
                  color=["steelblue", "darkorange", "gray", "lightgray"])
    ax.axhline(1.0, ls="--", color="black", lw=0.8, label="ATM IV = 1.0")
    ax.set_ylabel("IV / ATM IV at 16Δ")
    ax.set_title("Skew at 16Δ: fitted vs SPY defaults")
    for bar, val in zip(bars, [put_mult, call_mult, spy_put, spy_call]):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.002,
                f"{val:.3f}", ha="center", va="bottom", fontsize=9)
    ax.legend()

    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"  Saved → {out_path}")


def plot_stability(ann: pd.DataFrame, label: str, out_path: Path) -> None:
    if not HAS_PLT or ann.empty:
        return
    fig, axes = plt.subplots(1, 2, figsize=(12, 4))
    fig.suptitle(f"{label} — slope stability over years", fontsize=12)
    for ax, col, color in [
        (axes[0], "put_slope",  "steelblue"),
        (axes[1], "call_slope", "darkorange"),
    ]:
        ax.bar(ann["year"], ann[col], color=color, alpha=0.8, edgecolor="none")
        ax.axhline(ann[col].mean(), ls="--", color="black", lw=1,
                   label=f"mean={ann[col].mean():.3f}")
        ax.set_xlabel("year")
        ax.set_ylabel(col)
        ax.set_title(col)
        ax.legend()
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"  Saved → {out_path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def fit_market(underlying: str, min_year: int = 0, plots: bool = True) -> dict:
    label = underlying.upper()
    print(f"\n{'='*60}")
    print(f"Fitting {label}  (min_year={min_year or 'all'})")
    print(f"{'='*60}")

    df = load_chain(underlying, min_year)
    print(f"  Loaded      : {len(df):,} rows  "
          f"({df['date'].min().date()} → {df['date'].max().date()})")

    df = compute_atm_iv(df)
    print(f"  After ATM join: {len(df):,} rows  "
          f"({df['atm_iv'].notna().sum():,} with ATM ref)")

    put_slope, call_slope, diag = compute_slopes(df)
    print(f"\n  put_slope   = {put_slope:.4f}")
    print(f"  call_slope  = {call_slope:.4f}")

    # Context: what these slopes mean at 16Δ
    d16 = 0.50 - 0.16
    print(f"\n  16Δ put  IV multiplier : {1 + put_slope*d16:.4f}x ATM  "
          f"(SPY: {1 + 0.30*d16:.4f}x)")
    print(f"  16Δ call IV multiplier : {1 - call_slope*d16:.4f}x ATM  "
          f"(SPY: {1 - 0.10*d16:.4f}x)")

    # Residual quality
    puts  = diag[diag["leg"] == "put"]
    calls = diag[diag["leg"] == "call"]
    put_resid  = ((puts["iv_ratio"]  - 1) - put_slope  * puts["distance"]).abs().median()
    call_resid = ((1 - calls["iv_ratio"]) - call_slope * calls["distance"]).abs().median()
    print(f"\n  Median |residual| — put  : {put_resid:.4f}")
    print(f"  Median |residual| — call : {call_resid:.4f}")

    # Annual stability
    ann = annual_slopes(df)
    if not ann.empty:
        print(f"\n  Annual slopes (put / call):")
        for _, row in ann.iterrows():
            print(f"    {int(row['year'])}: {row['put_slope']:.3f} / {row['call_slope']:.3f}  "
                  f"(n={int(row['n']):,})")

    if plots:
        plot_diagnostics(diag, put_slope, call_slope, label,
                         OUT_DIR / f"skew_fit_{underlying}.png")
        if not ann.empty:
            plot_stability(ann, label,
                           OUT_DIR / f"skew_stability_{underlying}.png")

    return {"underlying": underlying, "put_slope": put_slope, "call_slope": call_slope}


def main():
    parser = argparse.ArgumentParser(description="Fit B3 vol skew slopes")
    parser.add_argument("--min-year", type=int, default=0,
                        help="Skip years before this (0 = all). "
                             "Recommended: 2017 for BOVA11 (thin earlier).")
    parser.add_argument("--no-plot", action="store_true")
    args = parser.parse_args()

    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"B3 options DB not found: {DB_PATH}\n"
            "Run: python scripts/build_b3_options_db.py"
        )

    results = {}
    for und in ("bova11", "petr4"):
        # Use 2017+ for BOVA11 (thin market before); all years for PETR4
        min_yr = max(args.min_year, 2017 if und == "bova11" else 0)
        results[und] = fit_market(und, min_year=min_yr, plots=not args.no_plot)

    print("\n" + "=" * 60)
    print("SUMMARY — paste into MARKET_PRESETS in src/straddle/params.py")
    print("=" * 60)
    for r in results.values():
        print(f'  "{r["underlying"]}": {{')
        print(f'      ...  # existing keys')
        print(f'      "put_slope":  {r["put_slope"]:.3f},')
        print(f'      "call_slope": {r["call_slope"]:.3f},')
        print(f'  }},')


if __name__ == "__main__":
    main()
