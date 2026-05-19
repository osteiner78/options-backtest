# 024 — Deploy Terminal-UI for Portfolio Showcase

**Date:** 2026-05-18
**Status:** Ready for execution
**Context:** The terminal-ui is functional. Deploy as a static site on GitHub Pages with two API backends: a free Render service for synthetic-only demos, and a home server LXC (via Wireguard + VPS + Caddy) for full B3 market data.

## Architecture

```
GitHub Pages (free static hosting)
    └── Terminal-UI (Vite build)
         ├── [Synthetic ▼] → Render free tier (synthetic-only API, no DB)
         └── [Full Market ▼] → Proxmox LXC via VPS reverse proxy (full rb3 DB)

Internet → VPS (104.168.120.158) → Caddy → Wireguard → Proxmox LXC
                                                          └── straddle.osteiner.xyz → API (port 8000)
```

## Phase 1 — Multi-backend API selector (terminal-ui)

### 1a. `apps/terminal-ui/src/store.js` — add API URL state

In `defaultParams`:
```js
apiBaseUrl: 'https://straddle-synth.onrender.com',
```

In a separate `uiConfig` object:
```js
apiOptions: [
  { value: 'https://straddle-synth.onrender.com', label: 'Synthetic (cloud)' },
  { value: 'https://straddle.osteiner.xyz',       label: 'Full Market (B3 real data)' },
  { value: 'http://localhost:8000',                label: 'Local (dev)' },
],
```

### 1b. `apps/terminal-ui/src/api/client.js` — use store's apiBaseUrl

Change the API base URL to read from the store at runtime:
```js
const apiBase = store.get('apiBaseUrl') || import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
```

### 1c. `apps/terminal-ui/src/components/topbar/TopBar.js` — add selector

Add a small `<select>` dropdown that changes `store.params.apiBaseUrl`. When the API is unreachable, show a subtle "offline" indicator next to the field.

### 1d. `apps/terminal-ui/src/components/sidebar/parameter-sections.js` — hide market selector in synthetic mode

When `apiBaseUrl` points to the Render instance, hide or disable the `market` selector (only synthetic mode is available without a DB). Add a note: "Real B3 market data requires the Full Market backend."

---

## Phase 2 — Update README.md for public repo

Replace the entire content of `README.md` with a compelling project overview:

```markdown
# B3 Short Strangle VRP — Backtesting Engine

[![Live Demo](https://img.shields.io/badge/Try%20it%20live-strangle%20backtest-blue)](https://<username>.github.io/options-backtest/)
[![Tests](https://img.shields.io/badge/tests-129%20passed-green)]()

Backtesting engine for selling OTM strangles on **BOVA11** (BVMF index ETF) and
**PETR4** (Petrobras) — Brazil's most liquid options market.

## What we found

A **volatility risk premium exists** and is reliably capturable on B3 at
mid-price execution. After 10,752 backtests across a 2,688-config grid:

| | BOVA11 | PETR4 |
|---|---:|---:|
| Configs profitable in holdout (mid) | 86.3% | 76.9% |
| Recommended config info ratio | **1.33** | **1.21** |
| Period robustness (data-rich windows) | 100% | 97.8% |

**Recommended config:** 25Δ / 21 DTE / 50% profit target / 21-DTE management /
mid execution / laddering mode. Commission-robust through 5× normal levels.

→ **Full analysis:** [`research/2026-05-15 - B3 - definitive research report.ipynb`](research/2026-05-15%20-%20B3%20-%20definitive%20research%20report.ipynb)

## How the research was done

Seven progressively refined grid searches (v1 → v7), starting from
parametric BSM pricing, through real B3 market data validation, to
full laddering-mode Reg-T margin accounting:

1. **Synthetic engine** — Black-Scholes with fitted B3 vol skew
2. **Market engine** — Real bid/ask from a 9.6 GB SQLite database (2015–2025, rb3)
3. **B3 bulletin validation** — rb3 settlement prices verified against
   B3's official daily bulletin (0.0% median mark difference)
4. **Execution sensitivity** — bid/ask, mid, mid+1tick tested across all configs
5. **Commission stress** — tested through 10× baseline (R$10/leg)
6. **Period robustness** — 5 rolling 3-year windows across both markets
7. **Manual P&L verification** — 9/9 trades match database marks to R$0.00

All bugs found across 7 code reviews are fixed. The codebase is production-grade.

## Architecture

```
params.py → data.py → engines.py → strategy.py → portfolio.py → metrics.py
                                             ↗
                              SyntheticEngine | MarketEngine
```

- **Two pricing engines** with a shared interface (synthetic BSM + real B3 bid/ask)
- **B3 market presets** override SPY defaults (CDI rates, BVMF calendar, BRL)
- **Laddering mode** via Reg-T margin accounting
- **FastAPI backend** with SSE progress streaming
- **Terminal-UI** deployed on GitHub Pages (uses the public Render API by default)

## Quick start

```bash
pip install -e ".[dev]"
pytest tests/ -v                                    # 129 tests
python scripts/run_backtest.py --market bova11      # CLI backtest
python scripts/run_v7_grid.py                       # grid search
```

## License

MIT
```

---

## Phase 3 — Deploy terminal-ui to GitHub Pages

### 3a. Build with the Render API as default

```bash
cd apps/terminal-ui
VITE_API_BASE_URL=https://straddle-synth.onrender.com npm run build
```

### 3b. Deploy dist/ to gh-pages branch

```bash
npx gh-pages -d dist
```

Or manually:
```bash
git checkout --orphan gh-pages
git rm -rf .
cp -r apps/terminal-ui/dist/* .
git add -A
git commit -m "deploy terminal-ui"
git push origin gh-pages --force
git checkout b3-backtest
```

### 3c. Configure GitHub Pages

In repo Settings → Pages:
- Source: Deploy from a branch
- Branch: `gh-pages`, `/ (root)`

The site will be live at `https://<username>.github.io/options-backtest/`.

---

## Phase 4 — Deploy synthetic-only API to Render

### 4a. Create a new Web Service on Render

| Field | Value |
|-------|-------|
| Name | `straddle-synth` |
| Runtime | Python 3 |
| Build Command | `pip install -e ".[api]"` |
| Start Command | `python scripts/run_api.py --port $PORT` |
| Plan | Free (512 MB RAM, no persistent disk, sleeps after 15 min idle) |

### 4b. Add CORS for GitHub Pages origin

In `src/straddle/api.py`, update the CORS middleware:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:*",
        "https://<username>.github.io",
        "https://straddle.osteiner.xyz",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### 4c. Prevent sleep (optional)

Render free tier sleeps after 15 minutes of inactivity. Register at UptimeRobot (free tier) and point a 10-minute ping to `https://straddle-synth.onrender.com/health`.

---

## Phase 5 — Home server LXC setup

### 5a. Create the LXC on Proxmox

| Resource | Value |
|----------|-------|
| OS | Ubuntu 24.04 LTS |
| RAM | 1 GB |
| Disk | 15 GB |
| CPU | 1 core |
| Network | Wireguard subnet (e.g., 10.0.0.10) |

### 5b. Install and configure

```bash
# Inside the new LXC:
apt update && apt install -y python3 python3-pip python3-venv git

# Clone the repo
git clone https://github.com/<username>/options-backtest.git /opt/straddle
cd /opt/straddle

# Install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[api]"

# Copy the rb3 database (from your NAS/storage — NOT in the repo)
# scp user@nas:/path/to/b3_options_rb3.db data/B3/

# Create systemd service
cat > /etc/systemd/system/straddle-api.service << 'EOF'
[Unit]
Description=Straddle Backtest API
After=network.target

[Service]
Type=simple
User=straddle
WorkingDirectory=/opt/straddle
ExecStart=/opt/straddle/.venv/bin/python scripts/run_api.py --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

useradd -r -s /bin/false straddle
chown -R straddle:straddle /opt/straddle
systemctl enable --now straddle-api
```

### 5c. Add Caddy reverse proxy on VPS

On the VPS, add to `/etc/caddy/Caddyfile`:

```caddy
straddle.osteiner.xyz {
    reverse_proxy 10.0.0.10:8000
}
```

Replace `10.0.0.10` with the LXC's Wireguard IP. Then:

```bash
caddy fmt --overwrite /etc/caddy/Caddyfile
systemctl reload caddy
```

### 5d. Verify

```bash
curl https://straddle.osteiner.xyz/health | jq .
# → {"status": "ok"}
```

---

## Phase 6 — Publicize & verify

### 6a. Update the API selector in terminal-ui

In `store.js`, change the `apiOptions` to use the real domain:

```js
apiOptions: [
  { value: 'https://straddle-synth.onrender.com', label: 'Synthetic (cloud)' },
  { value: 'https://straddle.osteiner.xyz',       label: 'Full Market (B3 real data)' },
  { value: 'http://localhost:8000',                label: 'Local (dev)' },
],
```

### 6b. Rebuild and redeploy

```bash
cd apps/terminal-ui && npm run build
npx gh-pages -d dist
```

### 6c. End-to-end test

1. Open `https://<username>.github.io/options-backtest/`
2. Select "Full Market (B3 real data)" from the API dropdown
3. Set BOVA11, 2023-01-02 → 2025-11-30, 25Δ, mid execution
4. Run — verify results appear within 30 seconds

---

## Summary

| Component | Service | Cost |
|-----------|---------|:----:|
| Frontend | GitHub Pages | Free |
| Synthetic API | Render free tier | Free |
| Full market API | Proxmox LXC + existing VPS | Free (uses existing infra) |
| rb3 database | Your NAS/storage | Free |
| **Total** | | **$0** |
