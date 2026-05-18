# B3 Options Short Strangle Backtest

BOVA11 and PETR4 short strangle backtesting engine with B3 options data
(rb3 database, 2015–2025).

## Strategy

Sells monthly OTM strangles (12–25Δ), mid-price execution, laddering mode,
Reg-T margin accounting. 21-DTE roll management, 50% profit target, 2.0x stop.

## Key Finding

VRP confirmed on both BOVA11 (86.3% configs positive in holdout at mid)
and PETR4 (76.9%). Recommended config: 25Δ / dte21 / pt50% / OFF / mid /
laddering. See `research/2026-05-15 - B3 - definitive research report.ipynb`
for the complete analysis.

## Quick Start

```bash
pip install -e ".[dev]"
pytest tests/ -v
python scripts/run_backtest.py --mode market --market bova11
python scripts/run_v7_grid.py
```
