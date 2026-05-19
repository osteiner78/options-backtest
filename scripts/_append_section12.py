#!/usr/bin/env python3
"""Append DTE30 deep-dive results to Section 11 of definitive notebook."""
import json, uuid

nb_path = "research/2026-05-15 - B3 - definitive research report.ipynb"
nb = json.loads(open(nb_path).read())
cells = nb["cells"]

# Find the Section 11 markdown cell
for i, c in enumerate(cells):
    src = "".join(c.get("source", []))
    if "## 11. Entry Cooldown Sensitivity" in src:
        # Append DTE30 deep-dive note before the code cell that follows
        # Find the code cell right after this markdown cell
        for j in range(i + 1, len(cells)):
            if cells[j]["cell_type"] == "code" and "Cross-reference" in "".join(cells[j].get("source", [])):
                # Insert a markdown sub-section before this code cell
                cells.insert(j, {
                    "cell_type": "markdown",
                    "id": str(uuid.uuid4()),
                    "metadata": {},
                    "source": [
                        "### DTE30 Deep-Dive (May 2026)\n",
                        "\n",
                        "**Full analysis:** `research/2026-05-18 - B3 - dte30 deep dive.ipynb`\n",
                        "\n",
                        "A follow-up deep-dive (Plan 023) tested dte30 with 5 cooldowns, 3 manage_at_dte values,\n",
                        "and 2 profit targets (60 backtests). The result was negative:\n",
                        "\n",
                        "- **No dte30 config achieves `min(IR_train, IR_holdout) > 1.20`.**\n",
                        "  Best stability config: `dte30/cd=3/mgr=14/pt=50%` — min_IR=0.63.\n",
                        "- **dte30 holdout IR (up to 1.45) does NOT translate to training IR (max 0.63).**\n",
                        "  All 30 configs show higher holdout than train IR — suggesting regime-dependence,\n",
                        "  not overfitting.\n",
                        "- **dte21/cd=3 remains the recommendation.** dte30 does not improve the IR-BPR frontier.\n",
                        "- Period robustness (Phase 3) was not triggered — no config passed the stability threshold.\n",
                        "\n",
                        "**Updated recommendation table (final):**\n",
                        "\n",
                        "| Config | Cooldown | manage_at_dte | pt | IR holdout | Avg BPR util | n_trades | Notes |\n",
                        "|--------|----------|----------------|-----|-----------|--------------|----------|-------|\n",
                        "| dte21/cd=3/mgr=14/pt=50% (v7) | 3 | 14 | 50% | 1.43 | ~28% | 135 | **Deployment recommendation** |\n",
                        "| dte30/cd=3/mgr=14/pt=50% | 3 | 14 | 50% | 1.33 | ~44% | 170 | Higher BPR but lower stability (min_IR=0.63) |\n",
                        "| dte30/cd=7/mgr=14/pt=50% | 7 | 14 | 50% | 1.45 | ~24% | 97 | Highest holdout IR but train IR=0.44 (unstable) |\n",
                        "\n",
                        "**Conclusion:** dte21/cd=3 remains the safest deployment choice. dte30 offers higher\n",
                        "capital efficiency but at the cost of cross-period stability. Further research into\n",
                        "pre-2018 or alternative market regimes would be needed to validate dte30 robustness.\n",
                    ],
                })
                print(f"DTE30 deep-dive note inserted at cell {j}")
                break
        break

with open(nb_path, "w") as f:
    json.dump(nb, f, indent=1, ensure_ascii=False)
print(f"Done. Total cells: {len(nb['cells'])}")
