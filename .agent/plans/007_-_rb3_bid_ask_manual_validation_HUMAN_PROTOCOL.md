# rb3 Bid/Ask Manual Validation — Human Protocol

**Estimated time:** 60–90 minutes
**Tools needed:** TradingView account (free is fine), spreadsheet (Excel/Sheets), the `validation_targets.csv` produced by the agent

---

## What you're doing and why

You need to verify that the `bid` and `ask` numbers in `b3_options_rb3.db` match what real B3 options were quoting at on specific days. If they match, the v4 grid search's "execute at bid/ask" scenario is meaningful (just pessimistic). If they don't match, the bid/ask data is noise and we should anchor conclusions on mid-price modes only.

This validation is **the single most important manual step** in the entire B3 research effort. If we don't do it, every conclusion about strategy profitability rests on an unverified data assumption.

---

## Step 1 — Get the validation targets from the agent

Before you can start, ask the coding agent to run a script that generates the targets. Tell it:

> Run `scripts/build_validation_targets.py` to produce `output/validation_targets.csv`. It should contain 20 rows: for each of the 10 dates in the v4 plan, find the BOVA11 option closest to 16-delta put and 16-delta call at the next monthly expiration. Output columns: date, type, strike, expiration, rb3_bid, rb3_ask, rb3_mark, rb3_delta, rb3_volume.

The output will look something like this:

```
date,        type, strike, expiration,   rb3_bid, rb3_ask, rb3_mark, rb3_delta, rb3_volume
2017-05-19, put,  56.0,   2017-06-19,   0.35,    0.45,    0.40,     -0.16,     1240
2017-05-19, call, 64.0,   2017-06-19,   0.30,    0.40,    0.35,     +0.16,     980
2018-10-31, put,  78.0,   2018-11-19,   ...      ...      ...       ...        ...
... (18 more rows)
```

Open it in a spreadsheet so you can fill in the TradingView columns as you go.

---

## Step 2 — Open TradingView and set up the options chain

1. Log into TradingView (https://www.tradingview.com/)
2. In the search bar, type `BOVA11` and select **BOVA11 · iShares Ibovespa Index Fund (BMFBOVESPA)**
3. You should land on the BOVA11 cash chart. Set the timeframe to **1 Day**.
4. Now you need to find the option chain. TradingView's option support varies by plan and by listing exchange. Try in this order:
   - **Easiest:** Right-side panel → look for "Options" tab. If it's there, great.
   - **Backup:** Top menu → "Products" → "Options & Derivatives" if your plan includes it.
   - **If neither works:** TradingView's BMF options coverage is limited. Skip to **Step 3-Alternative** below.

### Step 3 — For each row in `validation_targets.csv`, look up the historical EOD quote

**For each date, do this:**

#### A. Position the chart at the target date
1. On the BOVA11 daily chart, scroll/zoom to find the target date (e.g., 2017-05-19)
2. Hover your cursor over that exact daily bar — confirm the date stamp matches
3. The right-side panels should update to show "as-of" values for that date

#### B. Find the target contract
The contract you need is identified by:
- **Expiration:** Same as `validation_targets.csv` (e.g., 2017-06-19)
- **Strike:** Same (e.g., 56.0 for put or 64.0 for call)
- **Type:** Same (put or call)

In TradingView, the symbol convention for B3 options is:
- **Calls:** `BOVA` + month letter + strike code (e.g., `BOVAF56` for a June call at strike 56)
- **Puts:** `BOVA` + month letter + strike code, where put month letters are M-X

Month letter codes:
| Month | Call letter | Put letter |
|-------|------------|------------|
| Jan | A | M |
| Feb | B | N |
| Mar | C | O |
| Apr | D | P |
| May | E | Q |
| Jun | F | R |
| Jul | G | S |
| Aug | H | T |
| Sep | I | U |
| Oct | J | V |
| Nov | K | W |
| Dec | L | X |

So a June 2017 put at strike 56 = `BOVAR56`. Type that into TradingView's search bar.

#### C. Read the EOD values
Once you find the contract:
1. Set the chart to **1 Day** timeframe
2. Navigate to the validation date
3. Hover the cursor on the EOD bar — TradingView shows the OHLC values
4. **Important caveat about TradingView's option data:**
   - Many B3 options have very thin trading history in TradingView's database
   - The "bid" and "ask" fields may not be in the historical EOD view (TradingView often only stores last/close historically, not bid/ask)
   - If you can only get the **close/last** price, that's still useful — record it as `tv_close` and leave `tv_bid` and `tv_ask` blank

#### D. Record what you found
Fill in the spreadsheet:

```
date, type, strike, rb3_bid, tv_bid, rb3_ask, tv_ask, rb3_close, tv_close, rb3_volume, tv_volume, notes
2017-05-19, put, 56.0, 0.35, NA, 0.45, NA, 0.40, 0.42, 1240, NA, "TV close only"
```

Use `NA` if a value is unavailable.

#### E. If TradingView has nothing for that contract
This will happen often, especially for pre-2020 dates. Mark it as `notes="no data in TV"` and move on. Don't drop the row.

---

## Step 3-Alternative: If TradingView option chain access is too limited

You have three fallback paths. Pick whichever fits your time/budget.

### Alternative A: Use the **BOVA11 chart** alone (free, partial signal)

Even without option chains, you can validate **one critical thing**: the **underlying** close on each validation date. If rb3's `close_underlying` value matches TradingView's BOVA11 daily close exactly, that's evidence rb3's data pipeline is at least pulling the right rows for the right dates. It doesn't validate bid/ask, but it eliminates "is the date alignment wrong?" as a possibility.

Have the agent add `rb3_close_underlying` to `validation_targets.csv`, then compare against TradingView's BOVA11 daily close.

### Alternative B: Brapi.dev paid subscription (R$ 99.99 for one month)

If TradingView is too limited:

1. Subscribe to Brapi.dev (R$ 99.99 for a month — cancel after this validation)
2. Their endpoint: `https://brapi.dev/api/v2/inquire?range=...&interval=1d&fundamental=true&dividends=true&modules=...`
3. Check their documentation for historical option chain queries — they claim coverage since 2009
4. For each of the 20 contracts in your validation targets, call their API and record bid/ask/close
5. Save to spreadsheet exactly as the TradingView protocol describes

**This is the most reliable path** because Brapi.dev's data is direct from B3. If you can afford R$ 99.99, do this instead of TradingView.

### Alternative C: Brokerage research portal (free if you have an account)

If you have an account with **XP Investimentos** (you do — it's your PETR4 broker) or **Clear**, **BTG**, or **Inter**, their research portals sometimes include historical option chains. Log in, navigate to the options screener, and try to filter by date. Coverage varies.

### Alternative D: Reach out to a friend with Bloomberg

If you know anyone with terminal access: ask for 10 historical option chain snapshots. Each snapshot takes <1 minute to pull. Total imposition: 15 minutes of someone's time. The Bloomberg `OMON` function gives full historical option chains.

---

## Step 4 — Compute the validation metrics

Once you have data filled in (or marked NA), compute three numbers. You can do this in the spreadsheet directly:

### Metric 1 — Bid match rate

For each row with non-NA `tv_bid`:
```
bid_diff_pct = ABS(rb3_bid - tv_bid) / tv_bid
bid_match = 1 if bid_diff_pct < 0.10 else 0
```

Compute `bid_match_rate = AVERAGE(bid_match)` across non-NA rows.

### Metric 2 — Ask match rate

Same formula with `ask` instead of `bid`.

### Metric 3 — Close match rate

For each row with non-NA `tv_close`:
```
close_diff_pct = ABS(rb3_close - tv_close) / tv_close
close_match = 1 if close_diff_pct < 0.10 else 0
```

This is the most likely to be measurable because close prices are more commonly stored than bid/ask in free data sources.

---

## Step 5 — Interpret the results

| Outcome | Bid match | Ask match | Close match | Interpretation |
|---------|-----------|-----------|-------------|----------------|
| **PASS** | ≥80% | ≥80% | ≥80% | rb3 bid/ask data is reliable; v4 conclusions about bid_ask mode are valid |
| **PASS-CLOSE-ONLY** | NA | NA | ≥80% | rb3 mark/close data is reliable but bid/ask is unvalidated; anchor v4 conclusions on mid mode |
| **PARTIAL** | 50-80% | 50-80% | ≥80% | rb3 bid/ask is real but uses a different feed or time-of-day; use with caution |
| **FAIL** | <50% | <50% | <50% | Something is wrong with rb3 itself; investigate before any further conclusions |
| **FAIL-CLOSE-ONLY** | NA | NA | <50% | Even mark prices don't match — something is very wrong |

**Most likely outcomes given the limitations of free B3 option data:**

- **PASS-CLOSE-ONLY** is the realistic best case. We validate that rb3's date alignment and close prices are correct. We don't get to validate bid/ask. This is still useful — it means v4 conclusions from the `mid` execution mode are reliable.
- **PASS** (full validation) is possible only with Brapi.dev or a Bloomberg favor.

---

## Step 6 — Document the result

Open a new markdown file at `research/2026-05-14 - rb3 bid-ask external validation.md` and write:

```markdown
# rb3 Bid/Ask External Validation

**Validator:** [Your name]
**Date completed:** [today]
**Method:** Manual lookup via [TradingView / Brapi.dev / XP portal / etc.]
**Total time spent:** [X hours]

## Sample

| Field | Value |
|-------|-------|
| Dates checked | 10 |
| Contracts per date | 2 (16-delta put + 16-delta call) |
| Total contracts | 20 |
| TV data coverage | X of 20 contracts (Y%) |

## Results

### Bid match rate (±10% tolerance)
X / Z non-NA rows = AA%

### Ask match rate (±10% tolerance)
X / Z non-NA rows = AA%

### Close/mark match rate (±10% tolerance)
X / Z non-NA rows = AA%

## Decision

**[PASS / PASS-CLOSE-ONLY / PARTIAL / FAIL]**

## Detailed Comparison

[Paste the validation_comparison.csv table here, or attach as a file]

## Notes

- [Describe any patterns: dates where data was missing, contracts where rb3 and external source disagreed significantly]
- [Any sanity checks: did underlying close prices align? Were spreads in the expected range?]
- [Confidence level in the conclusion]

## What this means for v4 conclusions

[One paragraph summary: which P0A execution modes can be trusted, and which can't, based on this validation]
```

---

## Common pitfalls

1. **Date misalignment.** Brazil trades Mon-Fri but has different holidays from the US. If TradingView says "no data on 2018-10-31," check whether B3 was closed for a holiday (Bolsonaro election was Sunday, market reopened Monday). Use the actual trading day, not the calendar date.

2. **Strike rounding.** Some B3 strikes have decimal points (e.g., 55.50). TradingView may store these as `BOVAR55` (rounded) or `BOVAR5550`. If you can't find the exact strike, find the closest one and document the discrepancy.

3. **Adjusted vs unadjusted prices.** BOVA11 has had dividend distributions over 2017-2025. The strike on rb3's records is the **historical contract strike** (not adjusted). TradingView's historical chart is usually adjusted. This shouldn't affect the validation (you're comparing option prices, not equity prices), but be aware if numbers look off.

4. **Time of day.** rb3 likely captures the **official EOD settlement** from B3. TradingView's "last" may be the last trade before close, which is slightly different. Differences of a few centavos here are normal.

5. **Liquidity gaps.** On some validation dates, the 16-delta strike may not have traded at all that day. In that case, rb3's bid/ask are stale from a prior session. Document this as `notes="rb3 quote may be stale"`.

---

## When to escalate

If you find that **>50% of contracts show rb3-TV disagreement above 30%**, stop the validation and escalate. This is not a "PARTIAL" — it's a "something is very wrong" situation that needs investigation before any further work. The most likely cause would be:

- rb3 is pulling data from a different B3 product (e.g., BBOV11 mini-options instead of BOVA11 standard)
- rb3 has a date offset bug (data is shifted by one day or one session)
- TradingView is showing something other than EOD quotes
- The strike encoding in rb3 doesn't match B3's convention

Take it to a session with me (or with a coding agent) for diagnosis before proceeding to P0A.

---

## Bottom line

The validation is worth ~90 minutes of your time. Even if you can only get close/mark prices and not bid/ask (the realistic outcome with free tools), it eliminates the "is the data fundamentally wrong" question. After that, the v4 grid search will tell you whether the strategy has merit at any execution level.

If the validation result is PASS-CLOSE-ONLY, that's a perfectly defensible outcome — you proceed to interpret v4 results anchored on `mid` and `volume_filtered` modes, and you flag the `bid_ask` mode result as "indicative, not validated."
