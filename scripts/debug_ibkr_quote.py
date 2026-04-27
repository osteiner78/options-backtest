"""Diagnostic: test threadsafe option quote fetching.

Usage:
    python scripts/debug_ibkr_quote.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import ib_insync

ib_insync.util.patchAsyncio()
ib = ib_insync.IB()
ib.connect("127.0.0.1", 4002, clientId=77)

print(f"Connected: {ib.isConnected()}")
print(f"Loop: {ib.client._loop}")

async def run():
    # 1. Qualify a SPY option
    contract = ib_insync.Option("SPY", "20260515", 680, "P", "SMART", tradingClass="SPY")
    qualified = await ib.qualifyContractsAsync(contract)
    print(f"\nqualifyContractsAsync result: {qualified}")
    print(f"conId: {contract.conId}")

    if not contract.conId:
        print("ERROR: contract not qualified — no conId")
        return

    # 2. Try MIDPOINT history
    for what in ["MIDPOINT", "BID_ASK", "TRADES"]:
        for dur, bar in [("2 D", "1 hour"), ("5 D", "1 day")]:
            try:
                bars = await ib.reqHistoricalDataAsync(
                    contract,
                    endDateTime="",
                    durationStr=dur,
                    barSizeSetting=bar,
                    whatToShow=what,
                    useRTH=True,
                    formatDate=1,
                    keepUpToDate=False,
                )
                print(f"  {what} {dur}/{bar}: {len(bars)} bars  last={bars[-1].close if bars else 'none'}")
            except Exception as e:
                print(f"  {what} {dur}/{bar}: EXCEPTION {e}")

ib.run(run())
ib.disconnect()
