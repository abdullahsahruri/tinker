/*
 * bnn.js — the deployed TINKER network, bit-exact with scripts/bnn_reference.py.
 *
 *   28×28 → 2×2 average pool → 14×14 → four 7×7 quadrants
 *   → per-quadrant strict ">" median binarization (49 bits each)
 *   → layer 1 on the tile: 4 evaluations × 16 neurons,
 *        y = popcount(x XNOR w) >= θ
 *   → layer 2 in PicoRV32 firmware:
 *        logit[c] = 2·popcount(h XNOR w_c) − 64 + bias[c], argmax
 *
 * Pooling is done on integer 2×2 sums (0..1020), which orders pixels
 * exactly like the float means in the Python golden.
 * Works in the browser (window.TinkerBNN) and in Node (module.exports).
 */
(function (root) {
  "use strict";

  function pool14(img) {
    // img: length-784 array of 0..255 → length-196 integer sums
    const p = new Int32Array(196);
    for (let r = 0; r < 14; r++)
      for (let c = 0; c < 14; c++) {
        const i = 2 * r * 28 + 2 * c;
        p[r * 14 + c] = img[i] + img[i + 1] + img[i + 28] + img[i + 29];
      }
    return p;
  }

  function quadrants(p14) {
    // → 4 arrays of 49 values (q0 TL, q1 TR, q2 BL, q3 BR), row-major
    const q = [[], [], [], []];
    for (let r = 0; r < 14; r++)
      for (let c = 0; c < 14; c++)
        q[(r >= 7 ? 2 : 0) + (c >= 7 ? 1 : 0)].push(p14[r * 14 + c]);
    return q;
  }

  function binarize(q) {
    // strict > median; for 49 values the median is the 25th smallest
    const s = Array.from(q).sort((a, b) => a - b);
    const med = s[24];
    return q.map((v) => (v > med ? 1 : 0));
  }

  function xnorCount(x, w) {
    let n = 0;
    for (let j = 0; j < x.length; j++) if (x[j] === w[j]) n++;
    return n;
  }

  function parseModel(json) {
    const toBits = (s) => Array.from(s, (ch) => (ch === "1" ? 1 : 0));
    return {
      l1_w: json.l1_w.map(toBits),
      l1_t: json.l1_t,
      l2_w: json.l2_w.map(toBits),
      l2_bias: json.l2_bias,
    };
  }

  function forward(img, model) {
    const p14 = pool14(img);
    const quads = quadrants(p14).map(binarize);
    const hidden = new Array(64).fill(0);
    const counts = new Array(64).fill(0);
    for (let k = 0; k < 4; k++)
      for (let j = 0; j < 16; j++) {
        const n = 16 * k + j;
        counts[n] = xnorCount(quads[k], model.l1_w[n]);
        hidden[n] = counts[n] >= model.l1_t[n] ? 1 : 0;
      }
    const logits = model.l2_w.map(
      (w, c) => 2 * xnorCount(hidden, w) - 64 + model.l2_bias[c]
    );
    let pred = 0;
    for (let c = 1; c < 10; c++) if (logits[c] > logits[pred]) pred = c;
    return { p14, quads, counts, hidden, logits, pred };
  }

  const api = { parseModel, forward, pool14 };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.TinkerBNN = api;
})(typeof window !== "undefined" ? window : globalThis);
