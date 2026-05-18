#!/usr/bin/env python3
"""Append Section 11 (cooldown sensitivity cross-reference) to definitive notebook."""
import json, uuid

nb_path = "research/2026-05-15 - B3 - definitive research report.ipynb"
nb = json.loads(open(nb_path).read())
cells = nb["cells"]

# Update TOC
toc_src = "".join(cells[0]["source"])
if "11. Entry Cooldown Sensitivity" not in toc_src:
    toc_src = toc_src.replace(
        "10. [Final Recommendation](#10-final-recommendation)",
        "10. [Final Recommendation](#10-final-recommendation)\n11. [Entry Cooldown Sensitivity](#11-entry-cooldown-sensitivity)",
    )
    cells[0]["source"] = [toc_src]

# Section 11 markdown
cells.append({
    "cell_type": "markdown",
    "id": str(uuid.uuid4()),
    "metadata": {},
    "source": [
        "## 11. Entry Cooldown Sensitivity\n",
        "\n",
        "**Full analysis:** `research/2026-05-18 - B3 - entry cooldown sensitivity.ipynb`\n",
        "\n",
        "The v7 grid fixed `entry_cooldown_days=3`. A follow-up sensitivity analysis (May 2026)\n",
        "tested 5 cooldown values (1, 2, 3, 5, 7 days) x 3 DTE windows (21, 30, 45 days)\n",
        "against the recommended 25delta/pt50%/manage14/OFF/stop2.0/mid/laddering config.\n",
        "\n",
        "### Key Findings\n",
        "\n",
        "| Config | Cooldown | IR holdout | Avg BPR util | N trades | Notes |\n",
        "|--------|----------|------------|--------------|----------|-------|\n",
        "| dte21/cd3 | 3 | 1.43 | 27.8% | 135 | v7 baseline (in notebook) |\n",
        "| dte21/cd1 | 1 | 1.11 | 52.2% | 266 | 2x trades, higher BPR, IR >= 1.0 |\n",
        "| dte30/cd3 | 3 | 1.33 | 44.1% | 170 | Comparable IR to baseline, 2x BPR |\n",
        "| dte30/cd7 | 7 | 1.45 | 24.4% | 97 | Best IR overall, fewer trades |\n",
        "| dte21/cd5-7 | 5-7 | 1.78 | 15.4% | 71 | Highest IR, lowest capital deployment |\n",
        "\n",
        "### Updated Recommendation\n",
        "\n",
        "| Config | Cooldown | IR holdout | Avg BPR util | Use case |\n",
        "|--------|----------|------------|--------------|----------|\n",
        "| 25delta/dte21/pt50%/mid (v7 baseline) | 3 | 1.43 | ~28% | Conservative, proven |\n",
        "| 25delta/dte21/pt50%/mid (efficient) | 1 | 1.11 | ~52% | Aggressive, 2x trades |\n",
        "| 25delta/dte30/pt50%/mid (efficient) | 3 | 1.33 | ~44% | High IR + high BPR |\n",
        "\n",
        "**Conclusion:** The v7 baseline (cd=3) leaves significant capital idle (~72%).\n",
        "For deployment, consider `dte30/cd=3` (IR=1.33, 44% BPR) or `dte21/cd=1`\n",
        "(IR=1.11, 52% BPR). Both maintain IR >= 1.0 while materially improving\n",
        "capital efficiency. A follow-up deep-dive on `dte30` with\n",
        "`manage_at_dte in [7, 14]` is recommended to validate robustness.\n",
    ],
})

# Code cell with cross-reference
cells.append({
    "cell_type": "code",
    "id": str(uuid.uuid4()),
    "metadata": {},
    "source": [
        "# Cross-reference: full cooldown sensitivity notebook at\n",
        "# research/2026-05-18 - B3 - entry cooldown sensitivity.ipynb\n",
        "# (30 backtests, cells A-G, IR-BPR frontier, summary table)\n",
        "\n",
        "from pathlib import Path\n",
        "import pandas as pd\n",
        "\n",
        "cd_df = pd.read_parquet(ROOT / 'data' / 'B3' / 'v7_cooldown_sensitivity.parquet')\n",
        "cd_hold = cd_df[cd_df['period_label'] == 'holdout']\n",
        "cd_pivot = cd_hold.pivot_table(values='sharpe', index='dte_max', columns='entry_cooldown_days')\n",
        "print('IR by (dte_max x cooldown) -- holdout 2023-2025:')\n",
        "display(cd_pivot.style.format('{:.3f}'))\n",
        "\n",
        "cd_pivot_bpr = cd_hold.pivot_table(values='avg_bpr_util', index='dte_max', columns='entry_cooldown_days')\n",
        "print('Avg BPR Util (%) by (dte_max x cooldown) -- holdout:')\n",
        "display(cd_pivot_bpr.style.format('{:.1f}%'))\n",
    ],
    "outputs": [],
    "execution_count": None,
})

with open(nb_path, "w") as f:
    json.dump(nb, f, indent=1, ensure_ascii=False)

print(f"Section 11 appended. Total cells: {len(nb['cells'])}")
