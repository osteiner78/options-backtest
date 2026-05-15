# 005 — Fragile SQL Column Selection via F-String True/False

**Status:** resolved

## Symptom

In `MarketEngine._best_row()` (engines.py:809-810), the IV column was selected using:

```sql
CASE WHEN {use_cdi} THEN implied_volatility_cdi ELSE implied_volatility END
```

Where `use_cdi` is a Python `bool` formatted into the SQL string. This produced either
`CASE WHEN True THEN ...` or `CASE WHEN False THEN ...`. While `True`/`False` are
valid SQLite keywords (since 3.23.0), this approach is:
- Fragile: behavioral change if SQLite version is old
- Non-idiomatic: Python database code should use parameter binding or direct column
  name selection, not boolean literals injected into SQL

## Root Cause

The code used an f-string `{use_cdi}` to inject a Python bool into SQL, rather than
selecting the column name in Python and formatting the column name string.

## Fix Applied (engines.py:799-801)

```python
# Before:
use_cdi = self._use_cdi and self._has_cdi_cols
# ... CASE WHEN {use_cdi} THEN implied_volatility_cdi ELSE implied_volatility END

# After:
iv_col = "implied_volatility_cdi" if self._use_cdi and self._has_cdi_cols else "implied_volatility"
# ... {iv_col} AS implied_volatility
```

This directly selects the correct column name, eliminating the CASE WHEN entirely.
The `delta_col` selection already used this pattern.

## Verification

- All 90 tests pass
- The SQL query produces identical results (column name is selected before query execution)
