# SPY Short Strangle Backtest - GEMINI.md

## Project Overview
This project is a comprehensive backtesting engine for the **SPY short strangle** options strategy. It allows for systematic testing of selling monthly 16-delta put and call options, managing them at 21 DTE (rolling or closing), and applying various filters like VIX regimes.

### Main Technologies
- **Language:** Python 3.10+
- **Core Libraries:** `pandas`, `numpy`, `scipy`, `yfinance`
- **Visualization:** `matplotlib`, `seaborn`
- **UI/API:** `streamlit` (Frontend), `fastapi` (REST API)
- **Data Storage:** SQLite (Market data), Parquet (Cache)
- **Testing:** `pytest`

### Architecture
- `src/straddle/`: Core package containing all logic.
    - `params.py`: Centralized configuration (BACKTEST, STRATEGY, PRICING, OVERSHOOT).
    - `data.py`: Data loading and caching (Yahoo Finance).
    - `engines.py`: Pricing engines (Synthetic via Black-Scholes, Market via SQLite).
    - `strategy.py`: Trade mechanics (entry, exit, rolling, defensive adjustments).
    - `metrics.py`: Performance analysis (Sharpe, drawdown, win rate).
    - `plotting.py`: Visualization tools.
    - `api.py`: FastAPI implementation.
- `scripts/`: Entry points for CLI backtests and API server.
- `apps/`: Frontend applications.
    - `streamlit-ui/`: Streamlit web application.
    - `terminal-ui/`: Vite/Vanilla terminal interface.
- `tests/`: Comprehensive test suite for engines, strategy, and metrics.
- `data/`: Local data storage (SQLite DB and .gitkeep).

## Building and Running

### Setup
```bash
pip install -e ".[dev,frontend,api]"
```

### Running Backtests (CLI)
- **Synthetic Mode:** `python scripts/run_backtest.py --mode synthetic --start 2024-01-01 --end 2024-12-31`
- **Market Mode:** `python scripts/run_backtest.py --mode market`
- **Options:** Use `--no-plot` to skip chart generation.

### Web Interface (Streamlit)
```bash
streamlit run apps/streamlit-ui/app.py
```

### API Server
```bash
python scripts/run_api.py --port 8000
```

### Running Tests
```bash
pytest tests/ -v
```

## Development Conventions

### Configuration and Parameters
- All strategy "knobs" MUST be defined in `src/straddle/params.py`.
- The `PARAMS` dictionary is the source of truth for all modules.
- When adding new parameters, update the `TypedDict` schemas in `params.py`.

### Strategy Implementation
- Core trade logic resides in `src/straddle/strategy.py`. 
- New strategy features (e.g., different roll logic) should be implemented here and verified with new tests.
- Maintain the separation between `SyntheticEngine` and `MarketEngine` in `engines.py`.

### Testing Standards
- Every bug fix or feature addition MUST include a corresponding test in the `tests/` directory.
- Use fixtures in `tests/conftest.py` for shared data or mocks.
- Ensure "engine parity" (synthetic vs market results being reasonably close) is maintained when touching pricing logic.

### Coding Style
- Follow PEP 8 conventions.
- Use type hints for all function signatures and complex variables.
- Keep `src/straddle/__init__.py` as a clean facade for the public API.
