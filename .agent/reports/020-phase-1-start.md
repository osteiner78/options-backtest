# Phase 1 Start Report — Plan 020: Improve Code Quality

**Scope**: Safe cleanup across 6 source files — remove 9 temporary comments, replace 12 print() calls with logging, extract 12 named constants for magic numbers, and delete dead code (decorative phase banners + unused `_source_for_strike` method).

**Pre-work observations**:
- 129/129 tests pass at baseline.
- All 9 comments identified in the plan exist at the specified lines and are safe to remove/shorten.
- 13 total print() calls exist (12 substantive + 1 empty at plotting.py:367). The empty one will be removed; the other 12 converted to logging.
- `_source_for_strike` method (engines.py:1026–1044) is confirmed unreferenced — grep shows only its definition.
- The "Phase N" decorative banners at portfolio.py:33, 153, 248, 539 are cosmetic section dividers; safe to delete.
- GRUVBOX palette is defined but not used in `plot_backtest` — will note as follow-up for Phase 4.
- Markdown artifacts in plan (double-underscore for `__name__`, asterisk for multiply) are trivially resolved.
