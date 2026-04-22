/**
 * Chart utility functions for SVG generation.
 */

export const getVar = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

export const rnd = (min, max) => min + Math.random() * (max - min);

export const scaleY = (v, lo, hi, top, bot) => top + (1 - (v - lo) / (hi - lo)) * (bot - top);

export function generateMockEquityData(N = 55) {
  let pv = 0, sv = 0;
  const portPnl = [0], spyPnl = [0];
  for (let i = 1; i < N; i++) {
    pv += rnd(-0.4, 1.2);
    sv += rnd(-0.3, 1.0);
    portPnl.push(pv);
    spyPnl.push(sv);
  }
  const pScale = 84 / portPnl[N - 1];
  const sScale = 72 / spyPnl[N - 1];
  return {
    port: portPnl.map(v => v * pScale),
    spy: spyPnl.map(v => v * sScale),
    n: N
  };
}

export function generateMockBprData(N = 55) {
  let bpr = 0;
  const vals = [];
  for (let i = 0; i < N; i++) {
    bpr += rnd(-1.5, 2.0);
    bpr = Math.max(2, Math.min(42, bpr));
    vals.push(bpr);
  }
  return vals;
}

export function generateMockPositionsData(N = 55) {
  const vals = [];
  let p = 1;
  for (let i = 0; i < N; i++) {
    p += Math.random() < 0.3 ? (Math.random() < 0.5 ? 1 : -1) : 0;
    p = Math.max(0, Math.min(7, p));
    vals.push(p);
  }
  return vals;
}

export function generateMockVixData(N = 55) {
  const vals = [];
  let v = 18;
  for (let i = 0; i < N; i++) {
    v += rnd(-1.5, 1.5);
    v = Math.max(10, Math.min(55, v));
    if (Math.random() < 0.04) v = Math.min(55, v + rnd(8, 20));
    vals.push(v);
  }
  return vals;
}
