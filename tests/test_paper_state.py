"""Tests for paper trading state module."""

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from straddle.paper_trading.state import (
    StateStore,
    PaperTrade,
    PendingSignal,
    Notification,
    SignalType,
    SignalStatus
)


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    store = StateStore(db_path)
    yield store
    # Clean up
    Path(db_path).unlink(missing_ok=True)


def test_state_store_initialization(temp_db):
    """Test that StateStore initializes database with correct schema."""
    # Should create all tables without error
    # Verify by checking if we can query tables
    with temp_db._connect() as conn:
        tables = conn.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
        """).fetchall()
        table_names = {row[0] for row in tables}
        
        expected_tables = {
            "paper_trades", "leg_rolls", "equity_curve", "pending_signals",
            "heartbeat", "account_cache", "notifications", "auth_sessions"
        }
        assert table_names == expected_tables


def test_state_roundtrip(temp_db):
    """Test save/load roundtrip for PaperTrade."""
    # Create a trade
    trade = PaperTrade(
        entry_date=pd.Timestamp("2025-01-15"),
        expiration=pd.Timestamp("2025-02-21"),
        put_strike=450.0,
        call_strike=490.0,
        net_credit=650.0,
        status="open",
        daily_marks_json='[["2025-01-15", 650.0], ["2025-01-16", 620.0]]'
    )
    
    # Save trade
    trade_num = temp_db.save_trade(trade)
    assert trade_num == 1
    
    # Load trade back
    loaded = temp_db.load_trade(trade_num)
    assert loaded is not None
    assert loaded.trade_num == trade_num
    assert loaded.put_strike == 450.0
    assert loaded.call_strike == 490.0
    assert loaded.net_credit == 650.0
    assert loaded.status == "open"
    
    # Update trade
    loaded.status = "closed"
    loaded.exit_date = pd.Timestamp("2025-01-20")
    loaded.exit_type = "PROFIT"
    loaded.pnl = 300.0
    
    updated_num = temp_db.save_trade(loaded)
    assert updated_num == trade_num
    
    # Verify update
    updated = temp_db.load_trade(trade_num)
    assert updated.status == "closed"
    assert updated.exit_type == "PROFIT"
    assert updated.pnl == 300.0


def test_load_open_trades(temp_db):
    """Test loading open trades."""
    # Create open and closed trades
    open_trade = PaperTrade(
        entry_date=pd.Timestamp("2025-01-10"),
        expiration=pd.Timestamp("2025-02-21"),
        put_strike=440.0,
        call_strike=480.0,
        net_credit=600.0,
        status="open"
    )
    
    closed_trade = PaperTrade(
        entry_date=pd.Timestamp("2025-01-05"),
        expiration=pd.Timestamp("2025-01-17"),
        put_strike=445.0,
        call_strike=485.0,
        net_credit=580.0,
        status="closed",
        exit_date=pd.Timestamp("2025-01-15"),
        exit_type="STOP"
    )
    
    temp_db.save_trade(open_trade)
    temp_db.save_trade(closed_trade)
    
    # Load open trades
    open_trades = temp_db.load_open_trades()
    assert len(open_trades) == 1
    assert open_trades[0].put_strike == 440.0
    assert open_trades[0].status == "open"


def test_pending_signal_crud(temp_db):
    """Test CRUD operations for PendingSignal."""
    # Create a signal
    payload = {
        "put_strike": 450.0,
        "call_strike": 490.0,
        "expiration": "2025-02-21",
        "limit_price": 6.50,
        "ibkr_mid": 6.55,
        "bs_mid": 6.45
    }
    
    signal = PendingSignal(
        signal_type=SignalType.ENTRY,
        payload_json=json.dumps(payload)
    )
    
    # Enqueue signal
    signal_id = temp_db.enqueue_signal(signal)
    assert signal_id == 1
    
    # List signals
    signals = temp_db.list_signals()
    assert len(signals) == 1
    assert signals[0].id == signal_id
    assert signals[0].signal_type == SignalType.ENTRY
    assert signals[0].status == SignalStatus.PENDING
    
    # Update signal status
    updated = temp_db.update_signal_status(
        signal_id,
        SignalStatus.APPROVED,
        fill_json=json.dumps({"order_id": "12345", "avg_price": 6.48})
    )
    assert updated is True
    
    # Verify update
    signals = temp_db.list_signals(status=SignalStatus.APPROVED)
    assert len(signals) == 1
    assert signals[0].approved_at is not None
    assert signals[0].fill_json is not None


def test_signal_filtering(temp_db):
    """Test filtering signals by status and type."""
    # First create a trade for the foreign key constraint
    trade = PaperTrade(
        entry_date=pd.Timestamp("2025-01-10"),
        expiration=pd.Timestamp("2025-02-21"),
        put_strike=440.0,
        call_strike=480.0,
        net_credit=600.0,
        status="open"
    )
    trade_num = temp_db.save_trade(trade)
    
    # Create signals of different types and statuses
    entry_signal = PendingSignal(
        signal_type=SignalType.ENTRY,
        payload_json=json.dumps({"action": "entry"})
    )
    close_signal = PendingSignal(
        signal_type=SignalType.CLOSE,
        trade_num=trade_num,
        payload_json=json.dumps({"action": "close"})
    )
    roll_signal = PendingSignal(
        signal_type=SignalType.ROLL,
        trade_num=trade_num,
        payload_json=json.dumps({"action": "roll"})
    )
    
    # Add all signals
    entry_id = temp_db.enqueue_signal(entry_signal)
    close_id = temp_db.enqueue_signal(close_signal)
    roll_id = temp_db.enqueue_signal(roll_signal)
    
    # Approve the close signal
    temp_db.update_signal_status(close_id, SignalStatus.APPROVED)
    
    # Test filters
    pending_signals = temp_db.list_signals(status=SignalStatus.PENDING)
    assert len(pending_signals) == 2  # entry and roll
    
    approved_signals = temp_db.list_signals(status=SignalStatus.APPROVED)
    assert len(approved_signals) == 1
    assert approved_signals[0].signal_type == SignalType.CLOSE
    
    entry_signals = temp_db.list_signals(signal_type=SignalType.ENTRY)
    assert len(entry_signals) == 1
    assert entry_signals[0].id == entry_id


def test_heartbeat_operations(temp_db):
    """Test heartbeat tick and read operations."""
    # Initial heartbeat should be empty or default
    initial = temp_db.read_heartbeat()
    assert initial["last_tick_at"] is None
    
    # Tick heartbeat
    tick_time = pd.Timestamp("2025-01-15 16:30:00")
    temp_db.tick_heartbeat(
        last_eval_at=tick_time,
        ibkr_connected=True,
        open_trade_count=2
    )
    
    # Read heartbeat
    heartbeat = temp_db.read_heartbeat()
    assert heartbeat["last_tick_at"] is not None
    assert heartbeat["ibkr_connected"] is True
    assert heartbeat["open_trade_count"] == 2
    assert heartbeat["last_eval_at"] == tick_time


def test_account_cache_operations(temp_db):
    """Test account cache operations."""
    # Cache account summary
    summary = {
        "NetLiquidation": 52000.50,
        "BuyingPower": 38000.75,
        "TotalCashValue": 15000.25,
        "MaintMarginReq": 14000.0
    }
    
    temp_db.cache_account(summary)
    
    # Read cache
    cached_summary, updated_at = temp_db.read_account_cache()
    assert cached_summary is not None
    assert updated_at is not None
    assert cached_summary["NetLiquidation"] == 52000.50
    assert cached_summary["BuyingPower"] == 38000.75


def test_notification_crud(temp_db):
    """Test notification operations."""
    # Add notification
    notification = Notification(
        level="info",
        title="Test Notification",
        body="This is a test notification"
    )
    
    notification_id = temp_db.add_notification(notification)
    assert notification_id == 1
    
    # List notifications
    notifications = temp_db.list_notifications()
    assert len(notifications) == 1
    assert notifications[0].title == "Test Notification"
    assert notifications[0].read_at is None
    
    # Mark as read
    marked = temp_db.mark_notification_read(notification_id)
    assert marked is True
    
    # Check only unread
    unread = temp_db.list_notifications(unread_only=True)
    assert len(unread) == 0
    
    # All notifications should include the read one
    all_notifs = temp_db.list_notifications(unread_only=False)
    assert len(all_notifs) == 1
    assert all_notifs[0].read_at is not None


def test_auth_session_operations(temp_db):
    """Test authentication session operations."""
    # Create session
    token = "test_token_123"
    temp_db.create_session(token)
    
    # Validate session (should update last_used_at)
    valid = temp_db.validate_session(token)
    assert valid is True
    
    # Destroy session
    temp_db.destroy_session(token)
    
    # Should no longer be valid
    valid_again = temp_db.validate_session(token)
    assert valid_again is False


def test_equity_curve_operations(temp_db):
    """Test equity curve recording and retrieval."""
    # Record equity snapshots
    dates = [
        pd.Timestamp("2025-01-15"),
        pd.Timestamp("2025-01-16"),
        pd.Timestamp("2025-01-17")
    ]
    
    for i, date in enumerate(dates):
        temp_db.record_equity(
            date=date,
            nlv=50000.0 + i * 1000.0,
            cash=20000.0 + i * 500.0,
            source="MTM"
        )
    
    # Get equity curve
    curve = temp_db.get_equity_curve()
    assert len(curve) == 3
    
    # Check ordering (should be chronological)
    assert curve[0]["date"] == dates[0]
    assert curve[1]["date"] == dates[1]
    assert curve[2]["date"] == dates[2]
    
    # Check values
    assert curve[0]["nlv"] == 50000.0
    assert curve[1]["nlv"] == 51000.0
    assert curve[2]["nlv"] == 52000.0
    
    # Test date filtering
    filtered = temp_db.get_equity_curve(
        start_date=pd.Timestamp("2025-01-16"),
        end_date=pd.Timestamp("2025-01-17")
    )
    assert len(filtered) == 2
    assert filtered[0]["date"] == dates[1]
    assert filtered[1]["date"] == dates[2]


def test_signal_lifecycle(temp_db):
    """Test complete signal lifecycle."""
    # Create signal
    signal = PendingSignal(
        signal_type=SignalType.ENTRY,
        payload_json=json.dumps({"test": "data"})
    )
    
    signal_id = temp_db.enqueue_signal(signal)
    
    # Simulate lifecycle
    temp_db.update_signal_status(signal_id, SignalStatus.APPROVED)
    temp_db.update_signal_status(signal_id, SignalStatus.SUBMITTING)
    temp_db.update_signal_status(
        signal_id,
        SignalStatus.FILLED,
        fill_json=json.dumps({"fill_price": 6.50})
    )
    
    # Verify final state
    signals = temp_db.list_signals()
    assert len(signals) == 1
    final_signal = signals[0]
    
    assert final_signal.status == SignalStatus.FILLED
    assert final_signal.approved_at is not None
    assert final_signal.submitted_at is not None
    assert final_signal.executed_at is not None
    assert final_signal.fill_json is not None


def test_concurrent_access_simulation(temp_db):
    """Simulate concurrent access patterns."""
    # Add multiple trades and signals
    for i in range(5):
        trade = PaperTrade(
            entry_date=pd.Timestamp(f"2025-01-{10+i}"),
            expiration=pd.Timestamp("2025-02-21"),
            put_strike=450.0 + i,
            call_strike=490.0 + i,
            net_credit=600.0 + i * 10,
            status="open" if i < 3 else "closed"
        )
        temp_db.save_trade(trade)
        
        signal = PendingSignal(
            signal_type=SignalType.ENTRY if i % 2 == 0 else SignalType.CLOSE,
            trade_num=i+1 if i % 2 == 1 else None,
            payload_json=json.dumps({"iteration": i})
        )
        temp_db.enqueue_signal(signal)
    
    # Verify counts
    open_trades = temp_db.load_open_trades()
    assert len(open_trades) == 3
    
    closed_trades = temp_db.load_closed_trades()
    assert len(closed_trades) == 2
    
    signals = temp_db.list_signals()
    assert len(signals) == 5
    
    # Verify heartbeat reflects correct count
    temp_db.tick_heartbeat(open_trade_count=len(open_trades))
    heartbeat = temp_db.read_heartbeat()
    assert heartbeat["open_trade_count"] == 3