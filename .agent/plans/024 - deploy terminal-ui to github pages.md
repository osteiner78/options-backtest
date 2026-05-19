# 022 — Deploy Terminal-UI for Portfolio Showcase

**Date:** 2026-05-18
**Status:** Ready for execution
**Context:** The terminal-ui is functional. Deploy as a static site on GitHub Pages with
two API backends: a free Render service for synthetic-only demos, and the home server
(via Cloudflare Tunnel) for full B3 market data.

## Architecture

```
GitHub Pages (free static hosting)
    └── Terminal-UI (Vite build)
         ├── [Synthetic ▼] → Render free tier (synthetic-only API, no DB)
         └── [Full Market ▼] → Home server + Cloudflare Tunnel (full rb3 DB)
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
  { value: 'https://straddle-synth.onrender.com',  label: 'Synthetic (cloud)' },
  { value: 'https://straddle-full.example.com',     label: 'Full Market (self-hosted)' },
  { value: 'http://localhost:8000',                 label: 'Local (dev)' },
],
```

### 1b. `apps/terminal-ui/src/api/client.js` — use store's apiBaseUrl

Change the API base URL to read from the store at runtime:
```js
const apiBase = store.get('apiBaseUrl') || import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
```

Keep `VITE_API_BASE_URL` as the build-time fallback.

### 1c. `apps/terminal-ui/src/components/topbar/TopBar.js` — add selector

Add a small `<select>` dropdown that changes `store.params.apiBaseUrl`. When the API is unreachable, show a subtle "offline" indicator next to the field.

### 1d. `apps/terminal-ui/src/components/sidebar/parameter-sections.js` — hide market in synthetic

When `apiBaseUrl` points to the Render instance, hide or disable the `market` selector (only synthetic mode is available without a DB). Add a note: "Real B3 market data requires the Full Market backend."

---

## Phase 2 — Deploy to GitHub Pages

### 2a. Build

```bash
cd apps/terminal-ui
npm run build
```

### 2b. Deploy dist/ to gh-pages

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

### 2c. Configure GitHub Pages

In repo Settings → Pages:
- Source: Deploy from a branch
- Branch: `gh-pages`, `/ (root)`
- Custom domain: optional

The site will be live at `https://<username>.github.io/options-backtest/`.

---

## Phase 3 — Deploy synthetic-only API to Render

### 3a. Create a new Web Service on Render

| Field | Value |
|-------|-------|
| Name | `straddle-synth` |
| Runtime | Python 3 |
| Build Command | `pip install -e ".[api]"` |
| Start Command | `python scripts/run_api.py --port $PORT` |
| Plan | Free (512 MB RAM, no persistent disk, sleeps after 15 min idle) |

### 3b. Add CORS for GitHub Pages origin

In `src/straddle/api.py`, update the CORS middleware:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:*",
        "https://<username>.github.io",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### 3c. Verify synthetic-only mode works

The API should run without a database. When no `options_db_path` is configured (Render has no persistent disk), `make_engine` automatically falls back to `SyntheticEngine`.

```bash
curl -X POST https://straddle-synth.onrender.com/health | jq .
```

### 3d. Prevent sleep (optional)

Render free tier sleeps after 15 minutes of inactivity. Register at UptimeRobot (free tier) and point a 10-minute ping to `https://straddle-synth.onrender.com/health`.

---

## Phase 4 — Home server + Cloudflare Tunnel

### 4a. Install Cloudflare Tunnel

```bash
brew install cloudflare/cloudflare/cloudflared
cloudflared tunnel login
```

### 4b. Create tunnel

```bash
cloudflared tunnel create straddle
```

### 4c. Point DNS

```bash
cloudflared tunnel route dns straddle straddle-full.<your-domain>.com
```

Or use the free `*.trycloudflare.com` subdomain if you don't have a domain.

### 4d. Run the tunnel

```bash
cloudflared tunnel run straddle --url http://localhost:8000
```

This exposes your local `localhost:8000` API at `https://straddle-full.<domain>.com` with no port forwarding, no static IP, and no firewall changes.

### 4e. Run the API behind the tunnel

```bash
python scripts/run_api.py --port 8000
```

The API connects to the full rb3 database on your home server.

---

## Phase 5 — Demo mode refinements

### 5a. Add quick demo button

In the terminal-ui sidebar, add a "Quick Demo" button that fills in these defaults:

```js
{
  market: 'bova11',
  target_delta: 0.25,
  dte_min: 21,
  dte_max: 45,
  profit_target_pct: 0.5,
  execution_mode: 'mid',
  portfolio_mode: 'laddering',
  vix_filter: 'OFF',
  start_date: '2023-01-02',
  end_date: '2025-11-30',
  initial_balance: 100000,
}
```

### 5b. Link to research

Add a link in the topbar or a footer: "📊 Definitive Research Report" → GitHub repo link to the notebook.

### 5c. Repository badge

Add to `README.md`:
```markdown
[![Demo](https://img.shields.io/badge/Try%20it%20live-strangle%20backtest-blue)](https://<username>.github.io/options-backtest/)
```

---

## Verify

```bash
# 1. Terminal-ui builds without errors
cd apps/terminal-ui && npm run build

# 2. Synthetic backend responds
curl https://straddle-synth.onrender.com/health | jq .

# 3. GitHub Pages loads the static site
open https://<username>.github.io/options-backtest/

# 4. Run a backtest through the UI with Synthetic (cloud) selected

# 5. Switch to Full Market (if home server is up) and verify
```

## Summary

| Component | Service | Cost |
|-----------|---------|:----:|
| Frontend | GitHub Pages | Free |
| Synthetic API | Render free tier | Free |
| Home server API | Your machine + Cloudflare Tunnel | Free |
| rb3 database | Home server disk | Free |
| **Total** | | **$0** |
