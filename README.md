# B3 Short Strangle VRP — Backtesting Engine

[![Live Demo](https://img.shields.io/badge/Try%20it%20live-strangle%20backtest-blue)](https://<username>.github.io/options-backtest/)
[![Tests](https://img.shields.io/badge/tests-129%20passed-green)]()

Backtesting engine for selling OTM strangles on **BOVA11** (BVMF index ETF) and
**PETR4** (Petrobras) — Brazil's most liquid options market.

## What we found

A **volatility risk premium exists** and is reliably capturable on B3 at
mid-price execution. After 10,752 backtests across a 2,688-config grid:

| | BOVA11 | PETR4 |
|---|---:|---:|
| Configs profitable in holdout (mid) | 86.3% | 76.9% |
| Recommended config info ratio | **1.33** | **1.21** |
| Period robustness (data-rich windows) | 100% | 97.8% |

**Recommended config:** 25Δ / 21 DTE / 50% profit target / 21-DTE management /
mid execution / laddering mode. Commission-robust through 5× normal levels.

→ **Full analysis:** [`research/2026-05-15 - B3 - definitive research report.ipynb`](research/2026-05-15%20-%20B3%20-%20definitive%20research%20report.ipynb)

## How the research was done

Seven progressively refined grid searches (v1 → v7), starting from
parametric BSM pricing, through real B3 market data validation, to
full laddering-mode Reg-T margin accounting:

1. **Synthetic engine** — Black-Scholes with fitted B3 vol skew
2. **Market engine** — Real bid/ask from a 9.6 GB SQLite database (2015–2025, rb3)
3. **B3 bulletin validation** — rb3 settlement prices verified against
   B3's official daily bulletin (0.0% median mark difference)
4. **Execution sensitivity** — bid/ask, mid, mid+1tick tested across all configs
5. **Commission stress** — tested through 10× baseline (R$10/leg)
6. **Period robustness** — 5 rolling 3-year windows across both markets
7. **Manual P&L verification** — 9/9 trades match database marks to R$0.00

All bugs found across 7 code reviews are fixed. The codebase is production-grade.

## Architecture

```
params.py → data.py → engines.py → strategy.py → portfolio.py → metrics.py
                                             ↗
                              SyntheticEngine | MarketEngine
```

- **Two pricing engines** with a shared interface (synthetic BSM + real B3 bid/ask)
- **B3 market presets** override SPY defaults (CDI rates, BVMF calendar, BRL)
- **Laddering mode** via Reg-T margin accounting
- **FastAPI backend** with SSE progress streaming
- **Terminal-UI** deployed on GitHub Pages (uses the public Render API by default)

## Data files (not in git)

Large data lives in `data/` and is gitignored:

| File | Size | Used by |
|---|---|---|
| `data/Spy Options Database.db` | 9.6 GB | SPY market engine |
| `data/B3/b3_options_rb3.db` | 267 MB | B3 market engine (`params.py`), skew fit, deep-dive scripts |
| `data/B3/COTAHIST_A2010.ZIP` … `COTAHIST_A2026.ZIP` | 582 MB | raw B3 exchange files, only needed to rebuild data |

The raw COTAHIST files are stored **zipped** (one `.ZIP` per year, same layout as B3 publishes them;
the `.TXT` totalled 4.7 GB). `scripts/b3_parser.py` and `scripts/build_b3_options_db.py` read the
unzipped `COTAHIST_A*.TXT`, so unzip before rebuilding and delete the `.TXT` afterwards:

```bash
cd data/B3 && unzip -o 'COTAHIST_A*.ZIP'      # → COTAHIST_A*.TXT
# ... run the build/parsing scripts ...
rm COTAHIST_A*.TXT
```

The legacy `data/B3/b3_options.db` (built from COTAHIST, found corrupted — see
`.agent/plans/003 - migration_context.md`) was deleted on 2026-10-23; it is superseded by
`b3_options_rb3.db` and can be regenerated with `scripts/build_b3_options_db.py` if ever needed.

## Quick start

```bash
pip install -e ".[dev]"
pytest tests/ -v                                    # 129 tests
python scripts/run_backtest.py --market bova11      # CLI backtest
python scripts/run_v7_grid.py                       # grid search
```

## License

MIT
