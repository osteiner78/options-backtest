# Extended Commission Sensitivity - BOVA11 & PETR4

**Date:** 2026-05-15
**Baseline commission:** R$1.00/leg
**Multipliers tested:** [1, 2, 3, 5, 7, 10]
  (5x = R$5.00/leg, ~mid-range retail)
  (10x = R$10.00/leg, ~expensive retail)

---

## BOVA11

### Holdout Sharpe at mid execution

| config_label              |   1.0 |   2.0 |   3.0 |   5.0 |   7.0 |   10.0 |
|:--------------------------|------:|------:|------:|------:|------:|-------:|
| 16d/dte21/pt50%/rv_pct:70 |  1.93 |  1.63 |  1.38 |  0.5  | -0.57 |  -1.49 |
| 20d/dte21/pt50%/OFF       |  1.19 |  0.86 |  0.9  |  0.44 | -0.44 |  -0.82 |
| 20d/dte21/pt50%/rv_pct:80 |  1.48 |  1.15 |  1.23 |  0.94 |  0.01 |  -0.44 |
| 25d/dte21/pt50%/OFF       |  1.33 |  0.77 |  0.61 |  0.38 | -0.29 |  -0.54 |
| 25d/dte21/pt50%/rv_pct:80 |  1.6  |  0.91 |  0.74 |  0.66 | -0.19 |  -0.47 |

### Break-even commission multiplier (holdout, mid)

| Config | Last positive | Sharpe at 10x |
|--------|-------------|---------------|
| 16d/dte21/pt50%/rv_pct:70 | 5x | -1.49 |
| 20d/dte21/pt50%/OFF | 5x | -0.82 |
| 20d/dte21/pt50%/rv_pct:80 | 7x | -0.44 |
| 25d/dte21/pt50%/OFF | 5x | -0.54 |
| 25d/dte21/pt50%/rv_pct:80 | 5x | -0.47 |

### Holdout Sharpe at 10x commission by execution mode

| config_label              |   bid_ask |   mid |   mid_plus_1tick |
|:--------------------------|----------:|------:|-----------------:|
| 16d/dte21/pt50%/rv_pct:70 |     -4.27 | -1.49 |             0.37 |
| 20d/dte21/pt50%/OFF       |     -1.81 | -0.82 |             0.38 |
| 20d/dte21/pt50%/rv_pct:80 |     -1.97 | -0.44 |             0.89 |
| 25d/dte21/pt50%/OFF       |     -1.82 | -0.54 |             0.33 |
| 25d/dte21/pt50%/rv_pct:80 |     -2.06 | -0.47 |             0.61 |

## PETR4

### Holdout Sharpe at mid execution

| config_label              |   1.0 |   2.0 |   3.0 |   5.0 |   7.0 |   10.0 |
|:--------------------------|------:|------:|------:|------:|------:|-------:|
| 20d/dte21/pt50%/OFF       |  0.8  |  0.6  |  0.32 | -0.52 | -1.52 |  -3.28 |
| 25d/dte21/pt50%/OFF       |  1.21 |  0.99 |  0.67 | -0.37 | -1.01 |  -1.52 |
| 25d/dte21/pt50%/rv_pct:80 |  1.55 |  1.33 |  1.02 | -0.18 | -0.84 |  -1.44 |

### Break-even commission multiplier (holdout, mid)

| Config | Last positive | Sharpe at 10x |
|--------|-------------|---------------|
| 20d/dte21/pt50%/OFF | 3x | -3.28 |
| 25d/dte21/pt50%/OFF | 3x | -1.52 |
| 25d/dte21/pt50%/rv_pct:80 | 3x | -1.44 |

### Holdout Sharpe at 10x commission by execution mode

| config_label              |   bid_ask |   mid |   mid_plus_1tick |
|:--------------------------|----------:|------:|-----------------:|
| 20d/dte21/pt50%/OFF       |     -8.74 | -3.28 |            -0.6  |
| 25d/dte21/pt50%/OFF       |     -4.34 | -1.52 |            -0.63 |
| 25d/dte21/pt50%/rv_pct:80 |     -4.43 | -1.44 |            -0.45 |

---

## Appendix: Train Period (2018-2022)

### BOVA11 Train Sharpe at mid execution

| config_label              |   1.0 |   2.0 |   3.0 |   5.0 |   7.0 |   10.0 |
|:--------------------------|------:|------:|------:|------:|------:|-------:|
| 16d/dte21/pt50%/rv_pct:70 |  0.6  |  0.47 |  0.35 |  0.29 |  0.07 |  -0.26 |
| 20d/dte21/pt50%/OFF       |  0.72 |  0.59 |  0.5  |  0.67 |  0.67 |  -0.05 |
| 20d/dte21/pt50%/rv_pct:80 |  0.61 |  0.48 |  0.48 |  0.6  |  0.6  |  -0.08 |
| 25d/dte21/pt50%/OFF       |  0.9  |  0.77 |  0.7  |  0.56 |  0.38 |   0.04 |
| 25d/dte21/pt50%/rv_pct:80 |  0.77 |  0.62 |  0.56 |  0.45 |  0.38 |  -0.01 |

### PETR4 Train Sharpe at mid execution

| config_label              |   1.0 |   2.0 |   3.0 |   5.0 |   7.0 |   10.0 |
|:--------------------------|------:|------:|------:|------:|------:|-------:|
| 20d/dte21/pt50%/OFF       |  0.45 |  0.18 | -0.16 | -0.91 | -1.66 |  -2.66 |
| 25d/dte21/pt50%/OFF       |  0.62 |  0.28 |  0.18 | -0.34 | -0.83 |  -1.41 |
| 25d/dte21/pt50%/rv_pct:80 |  0.5  |  0.15 |  0.1  | -0.5  | -1.02 |  -1.42 |

