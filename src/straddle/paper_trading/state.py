"""SQLite persistence layer for paper trading.

Tables:
  paper_trades           - Open/closed trade history
  leg_rolls              - Defensive leg roll events
  equity_curve           - Daily net liquidation value
  pending_signals        - Entry/exit/roll signals awaiting approval/execution
  heartbeat              - Daemon health monitoring
  account_cache          - Cached IBKR account summary  
  notifications          - In-app notification feed
  auth_sessions          - Web UI authentication sessions
"""

import json
import sqlite3
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TypedDict
from dataclasses import asdict, dataclass, field

import pandas as pd

from straddle.strategy import Trade, LegRollEvent
from straddle.params import PARAMS


class SignalType(str, Enum):
    ENTRY = "ENTRY"
    CLOSE = "CLOSE"
    ROLL = "ROLL"
    LEG_ROLL = "LEG_ROLL"
    OPEN_RECOVERY = "OPEN_RECOVERY"
    MANUAL = "MANUAL"


class SignalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUBMITTING = "submitting"
    FILLED = "filled"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass
class PendingSignal:
    """A trading signal awaiting user approval and execution."""
    id: Optional[int] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    signal_type: SignalType = SignalType.ENTRY
    trade_num: Optional[int] = None
    payload_json: str = ""
    status: SignalStatus = SignalStatus.PENDING
    approved_at: Optional[datetime] = None
    submitted_at: Optional[datetime] = None
    executed_at: Optional[datetime] = None
    fill_json: Optional[str] = None
    error_msg: Optional[str] = None
    ibkr_perm_id: Optional[str] = None
    parent_signal_id: Optional[int] = None


@dataclass
class PaperTrade:
    """Simplified trade record for paper trading database."""
    trade_num: Optional[int] = None
    entry_date: pd.Timestamp = field(default_factory=pd.Timestamp.now)
    expiration: pd.Timestamp = field(default_factory=pd.Timestamp.now)
    put_strike: float = 0.0
    call_strike: float = 0.0
    net_credit: float = 0.0
    parent_trade_num: Optional[int] = None
    roll_count: int = 0
    status: str = "open"  # "open" | "closed" | "rolled"
    exit_date: Optional[pd.Timestamp] = None
    exit_type: Optional[str] = None  # "PROFIT" | "STOP" | "21DTE" | "EXPIRY" | "ROLLED"
    pnl: Optional[float] = None
    daily_marks_json: str = "[]"
    manual: bool = False
    ibkr_perm_id: Optional[str] = None
    # Extra strategy.Trade fields not in the main schema (put_mid_ps, call_mid_ps,
    # entry_vix, max_vix, stop_regime, overshoot_used, current strikes, etc.)
    metadata_json: str = "{}"


@dataclass
class Notification:
    """In-app notification."""
    id: Optional[int] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    level: str = "info"  # "info" | "warning" | "error" | "success"
    title: str = ""
    body: str = ""
    read_at: Optional[datetime] = None


class StateStore:
    """SQLite persistence for paper trading state."""
    
    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            db_path = str(Path(__file__).resolve().parent.parent.parent / "data" / "paper_trades.db")
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _connect(self) -> sqlite3.Connection:
        """Establish SQLite connection with WAL mode."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        # Enable WAL mode for concurrent access
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")  # 5 second timeout
        conn.execute("PRAGMA synchronous=NORMAL")  # Balance safety vs performance
        conn.execute("PRAGMA foreign_keys=ON")
        return conn
    
    def _init_db(self) -> None:
        """Initialize database schema."""
        with self._connect() as conn:
            # paper_trades
            conn.execute("""
                CREATE TABLE IF NOT EXISTS paper_trades (
                    trade_num INTEGER PRIMARY KEY AUTOINCREMENT,
                    entry_date TEXT NOT NULL,
                    expiration TEXT NOT NULL,
                    put_strike REAL NOT NULL,
                    call_strike REAL NOT NULL,
                    net_credit REAL NOT NULL,
                    parent_trade_num INTEGER,
                    roll_count INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'open',
                    exit_date TEXT,
                    exit_type TEXT,
                    pnl REAL,
                    daily_marks_json TEXT NOT NULL DEFAULT '[]',
                    manual BOOLEAN NOT NULL DEFAULT 0,
                    ibkr_perm_id TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY (parent_trade_num) REFERENCES paper_trades(trade_num)
                )
            """)
            
            # leg_rolls
            conn.execute("""
                CREATE TABLE IF NOT EXISTS leg_rolls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_num INTEGER NOT NULL,
                    event_date TEXT NOT NULL,
                    side TEXT NOT NULL,
                    old_strike REAL NOT NULL,
                    new_strike REAL NOT NULL,
                    debit_paid REAL NOT NULL,
                    data_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY (trade_num) REFERENCES paper_trades(trade_num) ON DELETE CASCADE
                )
            """)
            
            # equity_curve
            conn.execute("""
                CREATE TABLE IF NOT EXISTS equity_curve (
                    date TEXT PRIMARY KEY,
                    nlv REAL NOT NULL,
                    cash REAL NOT NULL,
                    open_trade_count INTEGER NOT NULL,
                    source TEXT NOT NULL  -- 'MTM' or 'IBKR_NLV'
                )
            """)
            
            # pending_signals
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pending_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    signal_type TEXT NOT NULL,
                    trade_num INTEGER,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    approved_at TEXT,
                    submitted_at TEXT,
                    executed_at TEXT,
                    fill_json TEXT,
                    error_msg TEXT,
                    ibkr_perm_id TEXT,
                    parent_signal_id INTEGER,
                    FOREIGN KEY (trade_num) REFERENCES paper_trades(trade_num),
                    FOREIGN KEY (parent_signal_id) REFERENCES pending_signals(id)
                )
            """)
            
            # heartbeat
            conn.execute("""
                CREATE TABLE IF NOT EXISTS heartbeat (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    last_tick_at TEXT NOT NULL,
                    last_eval_at TEXT,
                    ibkr_connected BOOLEAN NOT NULL DEFAULT 0,
                    open_trade_count INTEGER NOT NULL DEFAULT 0,
                    version TEXT NOT NULL DEFAULT '0.1.0',
                    dry_run BOOLEAN NOT NULL DEFAULT 0
                )
            """)
            
            # account_cache
            conn.execute("""
                CREATE TABLE IF NOT EXISTS account_cache (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    updated_at TEXT NOT NULL,
                    summary_json TEXT NOT NULL
                )
            """)
            
            # notifications
            conn.execute("""
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    level TEXT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    read_at TEXT
                )
            """)
            
            # auth_sessions
            conn.execute("""
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    token TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    last_used_at TEXT NOT NULL
                )
            """)
            
            # Schema migrations (ADD COLUMN IF NOT EXISTS via try/except — SQLite has no IF NOT EXISTS for columns)
            _migrations = [
                "ALTER TABLE heartbeat ADD COLUMN dry_run BOOLEAN NOT NULL DEFAULT 0",
                "ALTER TABLE paper_trades ADD COLUMN metadata_json TEXT",
                "ALTER TABLE leg_rolls ADD COLUMN data_json TEXT",
            ]
            for _sql in _migrations:
                try:
                    conn.execute(_sql)
                except Exception:
                    pass  # column already exists

            # Create indexes
            conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_trades_status ON paper_trades(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_paper_trades_parent ON paper_trades(parent_trade_num)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_leg_rolls_trade ON leg_rolls(trade_num)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pending_signals_status ON pending_signals(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pending_signals_created ON pending_signals(created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pending_signals_trade ON pending_signals(trade_num)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_notifications_read ON notifications(read_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_auth_sessions_last_used ON auth_sessions(last_used_at)")
            
            conn.commit()
    
    # ===== Trade Operations =====
    
    def save_trade(self, trade: PaperTrade) -> int:
        """Save or update a paper trade, return trade_num."""
        with self._connect() as conn:
            if trade.trade_num is None:
                # Insert new trade
                cursor = conn.execute("""
                    INSERT INTO paper_trades (
                        entry_date, expiration, put_strike, call_strike,
                        net_credit, parent_trade_num, roll_count, status,
                        exit_date, exit_type, pnl, daily_marks_json, manual, ibkr_perm_id,
                        metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    trade.entry_date.isoformat(),
                    trade.expiration.isoformat(),
                    trade.put_strike,
                    trade.call_strike,
                    trade.net_credit,
                    trade.parent_trade_num,
                    trade.roll_count,
                    trade.status,
                    trade.exit_date.isoformat() if trade.exit_date else None,
                    trade.exit_type,
                    trade.pnl,
                    trade.daily_marks_json,
                    1 if trade.manual else 0,
                    trade.ibkr_perm_id,
                    trade.metadata_json,
                ))
                trade_num = cursor.lastrowid
            else:
                # Update existing trade
                conn.execute("""
                    UPDATE paper_trades SET
                        entry_date = ?, expiration = ?, put_strike = ?, call_strike = ?,
                        net_credit = ?, parent_trade_num = ?, roll_count = ?, status = ?,
                        exit_date = ?, exit_type = ?, pnl = ?, daily_marks_json = ?,
                        manual = ?, ibkr_perm_id = ?, metadata_json = ?
                    WHERE trade_num = ?
                """, (
                    trade.entry_date.isoformat(),
                    trade.expiration.isoformat(),
                    trade.put_strike,
                    trade.call_strike,
                    trade.net_credit,
                    trade.parent_trade_num,
                    trade.roll_count,
                    trade.status,
                    trade.exit_date.isoformat() if trade.exit_date else None,
                    trade.exit_type,
                    trade.pnl,
                    trade.daily_marks_json,
                    1 if trade.manual else 0,
                    trade.ibkr_perm_id,
                    trade.metadata_json,
                    trade.trade_num,
                ))
                trade_num = trade.trade_num
            conn.commit()
            return trade_num
    
    def load_trade(self, trade_num: int) -> Optional[PaperTrade]:
        """Load a single trade by trade_num."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM paper_trades WHERE trade_num = ?",
                (trade_num,)
            ).fetchone()
            return self._row_to_paper_trade(row) if row else None
    
    def load_open_trades(self) -> List[PaperTrade]:
        """Load all open trades."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM paper_trades WHERE status = 'open' ORDER BY entry_date"
            ).fetchall()
            return [self._row_to_paper_trade(row) for row in rows]
    
    def load_closed_trades(self, limit: int = 100) -> List[PaperTrade]:
        """Load recently closed trades."""
        with self._connect() as conn:
            rows = conn.execute("""
                SELECT * FROM paper_trades 
                WHERE status = 'closed' 
                ORDER BY exit_date DESC 
                LIMIT ?
            """, (limit,)).fetchall()
            return [self._row_to_paper_trade(row) for row in rows]
    
    def _row_to_paper_trade(self, row: sqlite3.Row) -> PaperTrade:
        """Convert SQLite row to PaperTrade dataclass."""
        return PaperTrade(
            trade_num=row["trade_num"],
            entry_date=pd.Timestamp(row["entry_date"]),
            expiration=pd.Timestamp(row["expiration"]),
            put_strike=row["put_strike"],
            call_strike=row["call_strike"],
            net_credit=row["net_credit"],
            parent_trade_num=row["parent_trade_num"],
            roll_count=row["roll_count"],
            status=row["status"],
            exit_date=pd.Timestamp(row["exit_date"]) if row["exit_date"] else None,
            exit_type=row["exit_type"],
            pnl=row["pnl"],
            daily_marks_json=row["daily_marks_json"],
            manual=bool(row["manual"]),
            ibkr_perm_id=row["ibkr_perm_id"],
            metadata_json=row["metadata_json"] if row["metadata_json"] else "{}",
        )
    
    # ===== Signal Operations =====
    
    def enqueue_signal(self, signal: PendingSignal) -> int:
        """Enqueue a new signal, return signal ID."""
        with self._connect() as conn:
            cursor = conn.execute("""
                INSERT INTO pending_signals (
                    created_at, signal_type, trade_num, payload_json, status,
                    approved_at, submitted_at, executed_at, fill_json,
                    error_msg, ibkr_perm_id, parent_signal_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                signal.created_at.isoformat(),
                signal.signal_type.value,
                signal.trade_num,
                signal.payload_json,
                signal.status.value,
                signal.approved_at.isoformat() if signal.approved_at else None,
                signal.submitted_at.isoformat() if signal.submitted_at else None,
                signal.executed_at.isoformat() if signal.executed_at else None,
                signal.fill_json,
                signal.error_msg,
                signal.ibkr_perm_id,
                signal.parent_signal_id
            ))
            signal_id = cursor.lastrowid
            conn.commit()
            return signal_id
    
    def list_signals(
        self, 
        status: Optional[SignalStatus] = None,
        signal_type: Optional[SignalType] = None,
        limit: int = 100
    ) -> List[PendingSignal]:
        """List signals with optional filters."""
        query = "SELECT * FROM pending_signals WHERE 1=1"
        params = []
        
        if status:
            query += " AND status = ?"
            params.append(status.value)
        if signal_type:
            query += " AND signal_type = ?"
            params.append(signal_type.value)
        
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_pending_signal(row) for row in rows]
    
    def update_signal_status(
        self, 
        signal_id: int, 
        status: SignalStatus,
        error_msg: Optional[str] = None,
        fill_json: Optional[str] = None
    ) -> bool:
        """Update signal status, return True if updated."""
        with self._connect() as conn:
            # Set timestamps based on status transition
            set_clause = "status = ?"
            params = [status.value]
            
            now = datetime.now(timezone.utc).isoformat()
            if status == SignalStatus.APPROVED:
                set_clause += ", approved_at = ?"
                params.append(now)
            elif status == SignalStatus.SUBMITTING:
                set_clause += ", submitted_at = ?"
                params.append(now)
            elif status in (SignalStatus.FILLED, SignalStatus.CANCELLED, SignalStatus.FAILED):
                set_clause += ", executed_at = ?"
                params.append(now)
            
            if error_msg is not None:
                set_clause += ", error_msg = ?"
                params.append(error_msg)
            
            if fill_json is not None:
                set_clause += ", fill_json = ?"
                params.append(fill_json)
            
            params.append(signal_id)
            
            cursor = conn.execute(
                f"UPDATE pending_signals SET {set_clause} WHERE id = ?",
                params
            )
            updated = cursor.rowcount > 0
            conn.commit()
            return updated
    
    def _row_to_pending_signal(self, row: sqlite3.Row) -> PendingSignal:
        """Convert SQLite row to PendingSignal dataclass."""
        return PendingSignal(
            id=row["id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            signal_type=SignalType(row["signal_type"]),
            trade_num=row["trade_num"],
            payload_json=row["payload_json"],
            status=SignalStatus(row["status"]),
            approved_at=datetime.fromisoformat(row["approved_at"]) if row["approved_at"] else None,
            submitted_at=datetime.fromisoformat(row["submitted_at"]) if row["submitted_at"] else None,
            executed_at=datetime.fromisoformat(row["executed_at"]) if row["executed_at"] else None,
            fill_json=row["fill_json"],
            error_msg=row["error_msg"],
            ibkr_perm_id=row["ibkr_perm_id"],
            parent_signal_id=row["parent_signal_id"]
        )
    
    # ===== Heartbeat Operations =====
    
    def tick_heartbeat(
        self,
        last_eval_at: Optional[pd.Timestamp] = None,
        ibkr_connected: bool = True,
        open_trade_count: Optional[int] = None,
        dry_run: bool = False,
    ) -> None:
        """Update heartbeat row."""
        with self._connect() as conn:
            if open_trade_count is None:
                open_trade_count = conn.execute(
                    "SELECT COUNT(*) FROM paper_trades WHERE status = 'open'"
                ).fetchone()[0]

            conn.execute("""
                INSERT OR REPLACE INTO heartbeat (id, last_tick_at, last_eval_at, ibkr_connected, open_trade_count, version, dry_run)
                VALUES (1, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.now(timezone.utc).isoformat(),
                last_eval_at.isoformat() if last_eval_at else None,
                1 if ibkr_connected else 0,
                open_trade_count,
                "0.1.0",
                1 if dry_run else 0,
            ))
            conn.commit()
    
    def read_heartbeat(self) -> Dict[str, Any]:
        """Read current heartbeat status."""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM heartbeat WHERE id = 1").fetchone()
            if not row:
                return {"last_tick_at": None, "ibkr_connected": False, "open_trade_count": 0}
            
            return {
                "last_tick_at": datetime.fromisoformat(row["last_tick_at"]) if row["last_tick_at"] else None,
                "last_eval_at": datetime.fromisoformat(row["last_eval_at"]) if row["last_eval_at"] else None,
                "ibkr_connected": bool(row["ibkr_connected"]),
                "open_trade_count": row["open_trade_count"],
                "version": row["version"],
                "dry_run": bool(row["dry_run"]),
            }
    
    # ===== Account Cache Operations =====
    
    def cache_account(self, summary: Dict[str, Any]) -> None:
        """Cache IBKR account summary."""
        with self._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO account_cache (id, updated_at, summary_json)
                VALUES (1, ?, ?)
            """, (
                datetime.now(timezone.utc).isoformat(),
                json.dumps(summary)
            ))
            conn.commit()
    
    def read_account_cache(self) -> Tuple[Optional[Dict[str, Any]], Optional[datetime]]:
        """Read cached account summary and its update time."""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM account_cache WHERE id = 1").fetchone()
            if not row:
                return None, None
            
            return (
                json.loads(row["summary_json"]),
                datetime.fromisoformat(row["updated_at"])
            )
    
    # ===== Notification Operations =====
    
    def add_notification(self, notification: Notification) -> int:
        """Add a new notification, return notification ID."""
        with self._connect() as conn:
            cursor = conn.execute("""
                INSERT INTO notifications (created_at, level, title, body, read_at)
                VALUES (?, ?, ?, ?, ?)
            """, (
                notification.created_at.isoformat(),
                notification.level,
                notification.title,
                notification.body,
                notification.read_at.isoformat() if notification.read_at else None
            ))
            notification_id = cursor.lastrowid
            conn.commit()
            return notification_id
    
    def list_notifications(
        self, 
        unread_only: bool = False,
        limit: int = 50
    ) -> List[Notification]:
        """List notifications, optionally only unread ones."""
        query = "SELECT * FROM notifications"
        params = []
        
        if unread_only:
            query += " WHERE read_at IS NULL"
        
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_notification(row) for row in rows]
    
    def mark_notification_read(self, notification_id: int) -> bool:
        """Mark a notification as read."""
        with self._connect() as conn:
            cursor = conn.execute("""
                UPDATE notifications SET read_at = ? WHERE id = ?
            """, (
                datetime.now(timezone.utc).isoformat(),
                notification_id
            ))
            updated = cursor.rowcount > 0
            conn.commit()
            return updated
    
    def _row_to_notification(self, row: sqlite3.Row) -> Notification:
        """Convert SQLite row to Notification dataclass."""
        return Notification(
            id=row["id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            level=row["level"],
            title=row["title"],
            body=row["body"],
            read_at=datetime.fromisoformat(row["read_at"]) if row["read_at"] else None
        )
    
    # ===== Auth Session Operations =====
    
    def create_session(self, token: str) -> None:
        """Create a new authentication session."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO auth_sessions (token, created_at, last_used_at)
                VALUES (?, ?, ?)
            """, (token, now, now))
            conn.commit()
    
    def validate_session(self, token: str) -> bool:
        """Validate and update session timestamp."""
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cursor = conn.execute("""
                UPDATE auth_sessions 
                SET last_used_at = ?
                WHERE token = ? AND last_used_at > datetime(?, '-7 days')
            """, (now, token, now))
            valid = cursor.rowcount > 0
            conn.commit()
            return valid
    
    def destroy_session(self, token: str) -> None:
        """Destroy an authentication session."""
        with self._connect() as conn:
            conn.execute("DELETE FROM auth_sessions WHERE token = ?", (token,))
            conn.commit()
    
    def cleanup_expired_sessions(self) -> int:
        """Clean up sessions older than 7 days, return count removed."""
        week_ago = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cursor = conn.execute("""
                DELETE FROM auth_sessions 
                WHERE last_used_at < datetime(?, '-7 days')
            """, (week_ago,))
            removed = cursor.rowcount
            conn.commit()
            return removed
    
    # ===== Equity Curve Operations =====
    
    def record_equity(
        self,
        date: pd.Timestamp,
        nlv: float,
        cash: float,
        source: str = "MTM"
    ) -> None:
        """Record daily equity snapshot."""
        with self._connect() as conn:
            open_trade_count = conn.execute(
                "SELECT COUNT(*) FROM paper_trades WHERE status = 'open'"
            ).fetchone()[0]
            conn.execute("""
                INSERT OR REPLACE INTO equity_curve (date, nlv, cash, open_trade_count, source)
                VALUES (?, ?, ?, ?, ?)
            """, (
                date.isoformat(),
                nlv,
                cash,
                open_trade_count,
                source
            ))
            conn.commit()
    
    def get_equity_curve(
        self, 
        start_date: Optional[pd.Timestamp] = None,
        end_date: Optional[pd.Timestamp] = None
    ) -> List[Dict[str, Any]]:
        """Get equity curve data for a date range."""
        query = "SELECT * FROM equity_curve WHERE 1=1"
        params = []
        
        if start_date:
            query += " AND date >= ?"
            params.append(start_date.isoformat())
        if end_date:
            query += " AND date <= ?"
            params.append(end_date.isoformat())
        
        query += " ORDER BY date"
        
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [
                {
                    "date": pd.Timestamp(row["date"]),
                    "nlv": row["nlv"],
                    "cash": row["cash"],
                    "open_trade_count": row["open_trade_count"],
                    "source": row["source"]
                }
                for row in rows
            ]

    # ===== Leg Roll Operations =====

    def save_leg_roll(
        self,
        trade_num: int,
        event_date: pd.Timestamp,
        side: str,
        old_strike: float,
        new_strike: float,
        debit_paid: float,
        data_json: str = "{}",
    ) -> int:
        """Persist a leg roll event, return row id."""
        with self._connect() as conn:
            cursor = conn.execute("""
                INSERT INTO leg_rolls (trade_num, event_date, side, old_strike, new_strike, debit_paid, data_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (trade_num, event_date.isoformat(), side, old_strike, new_strike, debit_paid, data_json))
            conn.commit()
            return cursor.lastrowid

    def load_leg_rolls(self, trade_num: int) -> List[Dict[str, Any]]:
        """Return all leg roll events for a trade as raw dicts."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM leg_rolls WHERE trade_num = ? ORDER BY event_date",
                (trade_num,),
            ).fetchall()
            return [dict(row) for row in rows]

    # ===== Additional Trade Queries =====

    def load_all_trades(self, status: Optional[str] = None) -> List[PaperTrade]:
        """Load trades with optional status filter, newest first."""
        if status:
            rows = self._connect().execute(
                "SELECT * FROM paper_trades WHERE status = ? ORDER BY entry_date DESC",
                (status,),
            ).fetchall()
        else:
            rows = self._connect().execute(
                "SELECT * FROM paper_trades ORDER BY entry_date DESC"
            ).fetchall()
        return [self._row_to_paper_trade(row) for row in rows]

    def load_trades_in_range(
        self,
        start_date: pd.Timestamp,
        end_date: pd.Timestamp,
    ) -> List[PaperTrade]:
        """Return trades whose entry_date falls in [start_date, end_date)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM paper_trades WHERE entry_date >= ? AND entry_date < ? ORDER BY entry_date",
                (start_date.isoformat(), end_date.isoformat()),
            ).fetchall()
            return [self._row_to_paper_trade(row) for row in rows]