"""SPY short strangle backtesting engine.

Public API::

    from straddle import (
        PARAMS,
        load_market_data,
        SyntheticEngine,
        MarketEngine,
        make_engine,
        run_backtest,
        Trade,
        compute_metrics,
        plot_backtest,
        plot_engine_comparison,
        # Portfolio mode:
        PortfolioManager,
        calculate_reg_t_strangle_margin,
        run_portfolio_backtest,
        plot_portfolio_backtest,
        # Paper trading:
        StateStore,
        PaperTrade,
        PendingSignal,
        SignalType,
        SignalStatus,
        PaperConfig,
        Notifier,
        IBKRClient,
        MockIBKRClient,
        Fill,
        FillTimeout,
        is_quote_sane,
    )
"""

from straddle.params import PARAMS
from straddle.data import load_market_data, validate_market_mode_dates
from straddle.engines import SyntheticEngine, MarketEngine, make_engine
from straddle.strategy import run_backtest, Trade, LegRollEvent
from straddle.metrics import compute_metrics, compute_portfolio_metrics
from straddle.plotting import plot_backtest, plot_engine_comparison
from straddle.portfolio import (
    PortfolioManager,
    calculate_margin,
    calculate_reg_t_strangle_margin,
    calculate_iron_condor_margin,
    run_portfolio_backtest,
    plot_portfolio_backtest,
)

from straddle.paper_trading.state import (
    StateStore,
    PaperTrade,
    PendingSignal,
    SignalType,
    SignalStatus,
)
from straddle.paper_trading.config import PaperConfig
from straddle.paper_trading.notifications import Notifier
from straddle.paper_trading.ibkr_client import IBKRClient, MockIBKRClient, Fill, FillTimeout, is_quote_sane
from straddle.paper_trading.runner import PaperTradingEngine

__all__ = [
    "PARAMS",
    "load_market_data",
    "validate_market_mode_dates",
    "SyntheticEngine",
    "MarketEngine",
    "make_engine",
    "run_backtest",
    "Trade",
    "LegRollEvent",
    "compute_metrics",
    "compute_portfolio_metrics",
    "plot_backtest",
    "plot_engine_comparison",
    # Portfolio mode
    "PortfolioManager",
    "calculate_margin",
    "calculate_reg_t_strangle_margin",
    "calculate_iron_condor_margin",
    "run_portfolio_backtest",
    "plot_portfolio_backtest",
    # Paper trading
    "StateStore",
    "PaperTrade",
    "PendingSignal",
    "SignalType",
    "SignalStatus",
    "PaperConfig",
    "Notifier",
    "IBKRClient",
    "MockIBKRClient",
    "Fill",
    "FillTimeout",
    "is_quote_sane",
    "PaperTradingEngine",
]