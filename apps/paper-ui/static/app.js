/**
 * Paper Trading UI — shared JS
 *
 * Responsibilities:
 *  - Store / retrieve the Bearer token in localStorage ("paper_token").
 *  - Inject the token into every HTMX request header.
 *  - Redirect to /ui/login on 401.
 *  - Provide api() helper used by Alpine.js components.
 */

const TOKEN_KEY = "paper_token";

// ── Token helpers ─────────────────────────────────────────────────────────────

function getToken() {
  return localStorage.getItem(TOKEN_KEY) || "";
}

function setToken(t) {
  localStorage.setItem(TOKEN_KEY, t);
}

function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

// ── HTMX: inject Authorization header on every request ───────────────────────

document.addEventListener("htmx:configRequest", (evt) => {
  const token = getToken();
  if (token) {
    evt.detail.headers["Authorization"] = "Bearer " + token;
  }
});

document.addEventListener("htmx:responseError", (evt) => {
  if (evt.detail.xhr.status === 401) {
    clearToken();
    window.location.href = "/ui/login";
  }
});

// ── Fetch-based API helper used by Alpine components ─────────────────────────

async function api(method, path, body) {
  const opts = {
    method,
    headers: {
      "Content-Type": "application/json",
      Authorization: "Bearer " + getToken(),
    },
  };
  if (body !== undefined) opts.body = JSON.stringify(body);

  const res = await fetch(path, opts);
  if (res.status === 401) {
    clearToken();
    window.location.href = "/ui/login";
    return null;
  }
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  const ct = res.headers.get("content-type") || "";
  return ct.includes("application/json") ? res.json() : res.text();
}

// ── Alpine.js global store ────────────────────────────────────────────────────

document.addEventListener("alpine:init", () => {
  Alpine.store("health", {
    dryRun: false,
    ibkrConnected: false,
    heartbeatAgeSec: null,
    openTradeCount: 0,

    async refresh() {
      try {
        const d = await fetch("/health").then((r) => r.json());
        this.dryRun = d.dry_run;
        this.ibkrConnected = d.ibkr_connected;
        this.heartbeatAgeSec = d.heartbeat_age_sec;
        this.openTradeCount = d.open_trade_count;
      } catch (_) {}
    },
  });

  Alpine.store("notifications", {
    unreadCount: 0,
    async refresh() {
      if (!getToken()) return;
      try {
        const ns = await api("GET", "/notifications?unread=true");
        this.unreadCount = ns ? ns.length : 0;
      } catch (_) {}
    },
  });
});

// Poll health every 10 s (works on login page too — no auth needed)
setInterval(() => {
  if (window.Alpine) {
    Alpine.store("health").refresh();
    Alpine.store("notifications").refresh();
  }
}, 10_000);

window.addEventListener("load", () => {
  if (window.Alpine) {
    Alpine.store("health").refresh();
    Alpine.store("notifications").refresh();
  }
});
