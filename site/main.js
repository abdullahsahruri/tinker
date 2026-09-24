/* TINKER explainer — scroll engine, animations, and the live-network lab.
 * No dependencies. Everything degrades to a static page under
 * prefers-reduced-motion. */
(function () {
  "use strict";

  const REDUCED = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const SVGNS = "http://www.w3.org/2000/svg";
  const svg = (tag, attrs = {}, parent) => {
    const el = document.createElementNS(SVGNS, tag);
    for (const k in attrs) el.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(el);
    return el;
  };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  // Deterministic PRNG so the illustrations look the same on every visit.
  function rng(seed) {
    return function () {
      seed |= 0; seed = (seed + 0x6D2B79F5) | 0;
      let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function tween(from, to, ms, onStep, done) {
    if (REDUCED || ms <= 0) { onStep(to); if (done) done(); return; }
    const t0 = performance.now();
    (function frame(now) {
      const k = Math.min(1, (now - t0) / ms);
      const e = 1 - Math.pow(1 - k, 3);
      onStep(from + (to - from) * e);
      if (k < 1) requestAnimationFrame(frame); else if (done) done();
    })(t0);
  }

  /* ------------------------------------------------------------------ */
  /* Scroll progress + reveal + counters                                 */
  /* ------------------------------------------------------------------ */
  const bar = $("#progress");
  function onScroll() {
    const h = document.documentElement;
    const p = h.scrollTop / Math.max(1, h.scrollHeight - h.clientHeight);
    bar.style.width = (p * 100).toFixed(2) + "%";
  }
  document.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  const revealIO = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      e.target.classList.add("in");
      e.target.dispatchEvent(new CustomEvent("revealed"));
      revealIO.unobserve(e.target);
    }
  }, { threshold: 0.15 });
  $$(".reveal, .reveal-clip, .tile-anim").forEach((el) => revealIO.observe(el));

  $$(".count").forEach((el) => {
    const to = parseFloat(el.dataset.to), dec = +el.dataset.dec;
    const host = el.closest(".reveal") || el;
    host.addEventListener("revealed", () =>
      tween(0, to, 1400, (v) => (el.textContent = v.toFixed(dec))), { once: true });
  });

  /* ------------------------------------------------------------------ */
  /* Hero: drifting bit field                                            */
  /* ------------------------------------------------------------------ */
  (function hero() {
    const cv = $("#hero-bits");
    if (!cv || REDUCED) return;
    const ctx = cv.getContext("2d");
    const rand = rng(7);
    let cols = [], W = 0, H = 0, running = true, dpr = 1;
    const CELL = 22;
    function resize() {
      dpr = Math.min(2, window.devicePixelRatio || 1);
      W = cv.clientWidth; H = cv.clientHeight;
      cv.width = W * dpr; cv.height = H * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      cols = [];
      for (let x = 0; x < W / CELL; x++)
        cols.push({ y: rand() * H, v: 12 + rand() * 30, bits: Array.from({ length: 40 }, () => rand() > .5) });
    }
    resize();
    window.addEventListener("resize", resize);
    new IntersectionObserver(([e]) => { running = e.isIntersecting; if (running) requestAnimationFrame(tick); }).observe(cv);
    let last = performance.now();
    function tick(now) {
      if (!running) return;
      const dt = Math.min(0.05, (now - last) / 1000); last = now;
      ctx.clearRect(0, 0, W, H);
      ctx.font = "600 13px ui-monospace, Menlo, monospace";
      const navy = css("--navy-5"), red = css("--tile");
      cols.forEach((c, i) => {
        c.y += c.v * dt;
        if (c.y > H + 40 * CELL) c.y = -rand() * H;
        for (let k = 0; k < c.bits.length; k++) {
          const y = c.y - k * CELL;
          if (y < -CELL || y > H + CELL) continue;
          const fade = 1 - k / c.bits.length;
          const hot = k === 0;
          ctx.globalAlpha = hot ? 0.9 : 0.35 * fade;
          ctx.fillStyle = hot ? red : navy;
          ctx.fillText(c.bits[(k + i) % c.bits.length] ? "1" : "0", i * CELL + 4, y);
        }
      });
      ctx.globalAlpha = 1;
      requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  })();

  /* ------------------------------------------------------------------ */
  /* 01: a classic threshold gate that fires                             */
  /* ------------------------------------------------------------------ */
  (function tlg() {
    const g = $("#tlg-svg .tlg-inputs");
    if (!g) return;
    const W = [2, -1, 3, 1, -2], TH = 3, N = W.length;
    const dots = [];
    const out = $("#tlg-svg .tlg-out");
    for (let i = 0; i < N; i++) {
      const y = 30 + i * 35;
      svg("line", { x1: 36, y1: y, x2: 266, y2: 100 + (y - 100) * 0.35, class: "tlg-in-line" }, g);
      dots.push(svg("circle", { cx: 26, cy: y, r: 9, class: "tlg-in-dot" }, g));
      const t = svg("text", { x: 120, y: y - 6 + (100 - y) * 0.18, class: "tlg-w" }, g);
      t.textContent = "w=" + (W[i] > 0 ? "+" : "") + W[i];
    }
    const rand = rng(3);
    let alive = false;
    new IntersectionObserver(([e]) => { alive = e.isIntersecting; if (alive) loop(); }).observe(g.ownerSVGElement);
    async function loop() {
      while (alive) {
        const x = dots.map(() => (rand() > .45 ? 1 : 0));
        let s = 0;
        dots.forEach((d, i) => { d.classList.toggle("on", !!x[i]); s += W[i] * x[i]; });
        out.classList.toggle("fire", s >= TH);
        if (REDUCED) return;
        await sleep(1300);
      }
    }
  })();

  /* ------------------------------------------------------------------ */
  /* 02: interactive neuron                                              */
  /* ------------------------------------------------------------------ */
  (function neuron() {
    const root = $("#neuron-demo");
    if (!root) return;
    const rand = rng(11);
    let x = [], w = [], theta = 32;
    const ex = $("#nd-x"), ew = $("#nd-w"), exn = $("#nd-xn");
    function build(host, arr, editable) {
      host.innerHTML = "";
      arr.forEach((b, i) => {
        const el = document.createElement(editable ? "button" : "span");
        el.className = "bit" + (b ? " on" : "");
        if (editable) {
          el.type = "button";
          el.setAttribute("aria-label", "bit " + i);
          el.addEventListener("click", () => { arr[i] ^= 1; el.classList.toggle("on"); update(i); });
        }
        host.appendChild(el);
      });
    }
    function randomize() {
      x = Array.from({ length: 64 }, () => (rand() > .5 ? 1 : 0));
      // bias agreement so the count lands near the threshold
      w = x.map((b) => (rand() < .55 ? b : 1 - b));
      build(ex, x, true); build(ew, w, true);
      build(exn, x.map((b, i) => +(b === w[i])), false);
      update();
    }
    function update(flashIdx) {
      const xn = x.map((b, i) => +(b === w[i]));
      const cells = exn.children;
      xn.forEach((v, i) => cells[i].classList.toggle("on", !!v));
      if (flashIdx !== undefined && !REDUCED) {
        cells[flashIdx].classList.add("flash");
        setTimeout(() => cells[flashIdx].classList.remove("flash"), 220);
      }
      const n = xn.reduce((a, b) => a + b, 0);
      $("#nd-count").textContent = n;
      $("#nd-fill").style.width = (n / 64 * 100) + "%";
      $("#nd-theta-mark").style.left = `calc(${theta / 64 * 100}% - 1.5px)`;
      $("#nd-theta-v").textContent = theta;
      $("#nd-y").classList.toggle("on", n >= theta);
    }
    $("#nd-theta").addEventListener("input", (e) => { theta = +e.target.value; update(); });
    $("#nd-rand").addEventListener("click", randomize);
    randomize();
    // On first view, sweep the XNOR row so the reader sees it being computed.
    root.addEventListener("revealed", async () => {
      if (REDUCED) return;
      const cells = exn.children;
      for (let i = 0; i < 64; i++) {
        cells[i].classList.add("flash");
        setTimeout(() => cells[i].classList.remove("flash"), 200);
        await sleep(18);
      }
    }, { once: true });
  })();

  /* ------------------------------------------------------------------ */
  /* Scrolly engine                                                      */
  /* ------------------------------------------------------------------ */
  const scrollyHandlers = {};
  function initScrolly() {
    $$("[data-scrolly]").forEach((sec) => {
      const name = sec.dataset.scrolly;
      const steps = $$(".step", sec);
      let current = -1;
      const io = new IntersectionObserver((entries) => {
        for (const e of entries) {
          if (!e.isIntersecting) continue;
          const s = +e.target.dataset.step;
          if (s === current) continue;
          current = s;
          steps.forEach((st) => st.classList.toggle("active", st === e.target));
          if (scrollyHandlers[name]) scrollyHandlers[name](s);
        }
      }, { rootMargin: window.matchMedia("(max-width: 820px)").matches ? "-62% 0px -30% 0px" : "-45% 0px -45% 0px" });
      steps.forEach((st) => io.observe(st));
      if (scrollyHandlers[name]) scrollyHandlers[name](0);
    });
  }

  /* ------------------------------------------------------------------ */
  /* 03: chunked-LUT decomposition                                       */
  /* ------------------------------------------------------------------ */
  (function decomp() {
    const S = $("#dc-svg");
    if (!S) return;
    const rand = rng(5);
    const bits = Array.from({ length: 64 }, () => (rand() < .58 ? 1 : 0));
    const THETA = 32;
    const CH = [];                      // chunk index → [start, len]
    for (let c = 0; c < 10; c++) CH.push([6 * c, 6]);
    CH.push([60, 4]);
    const chunkOf = (i) => Math.min(10, Math.floor(i / 6));

    // Layouts.
    const ROW_Y = 40, CS = 10, ST = 12;
    const rowX = (i) => 18 + i * 13.4;                      // state 0: one long row
    const chunkX0 = (c) => 13 + c * 82;                     // state ≥1: grouped
    const groupedX = (i) => { const c = chunkOf(i); return chunkX0(c) + 3 + (i - CH[c][0]) * ST; };
    const chunkW = (c) => CH[c][1] * ST + 4;
    const chunkCX = (c) => chunkX0(c) + chunkW(c) / 2 + 1;

    // Fan-in lines for the "naive" picture (state 0).
    const fan = svg("g", { class: "fanin" }, S);
    const naiveNode = { x: 450, y: 300 };
    for (let i = 0; i < 64; i++)
      svg("line", { x1: rowX(i) + CS / 2, y1: ROW_Y + CS, x2: naiveNode.x, y2: naiveNode.y, class: "dc-edge vis" }, fan);
    svg("circle", { cx: naiveNode.x, cy: naiveNode.y, r: 44, class: "dc-node vis" }, fan);
    const nt = svg("text", { x: naiveNode.x, y: naiveNode.y + 6, class: "dc-node-t vis" }, fan);
    nt.textContent = "Σ of 64";
    const nl = svg("text", { x: naiveNode.x, y: naiveNode.y + 78, class: "dc-label", "text-anchor": "middle" }, fan);
    nl.textContent = "64-input summing node: needs an analog primitive";

    // Chunk frames + subcount labels.
    const chunkRects = CH.map((_, c) => svg("rect", { x: chunkX0(c), y: ROW_Y - 6, width: chunkW(c), height: CS + 12, rx: 5, class: "dc-chunk" }, S));
    const subcounts = CH.map(([s, len]) => bits.slice(s, s + len).reduce((a, b) => a + b, 0));
    const countY = ROW_Y + CS + 34;
    const countT = CH.map((_, c) => {
      const t = svg("text", { x: chunkCX(c), y: countY, class: "dc-count" }, S);
      t.textContent = subcounts[c];
      return t;
    });
    const lutT = CH.map((_, c) => {
      const t = svg("text", { x: chunkCX(c), y: countY + 19, class: "dc-count", style: "font-size:12px;font-weight:500" }, S);
      t.textContent = (CH[c][1] === 6 ? "6→3" : "4→3");
      return t;
    });

    // Bits on top.
    const bitEls = bits.map((b, i) => svg("rect", { x: rowX(i), y: ROW_Y, width: CS, height: CS, rx: 2, class: "dc-bit " + (b ? "on" : "off") }, S));
    const topLabel = svg("text", { x: 18, y: 22, class: "dc-label" }, S);

    // Adder tree.
    const tree = svg("g", {}, S);
    const levels = [];
    let prev = CH.map((_, c) => ({ x: chunkCX(c), y: countY + 26, v: subcounts[c] }));
    const LY = [158, 230, 300, 368];
    for (let L = 0; L < 4; L++) {
      const next = [];
      for (let i = 0; i < prev.length; i += 2) {
        const a = prev[i], b = prev[i + 1];
        const n = { x: b ? (a.x + b.x) / 2 : a.x, y: LY[L], v: a.v + (b ? b.v : 0) };
        [a, b].forEach((ch) => ch && svg("path", { d: `M${ch.x} ${ch.y + (L ? 16 : 0)} L${n.x} ${n.y - 16}`, class: "dc-edge tree-el" }, tree));
        next.push(n);
      }
      next.forEach((n) => {
        svg("rect", { x: n.x - 26, y: n.y - 16, width: 52, height: 32, rx: 8, class: "dc-node tree-el" }, tree);
        const t = svg("text", { x: n.x, y: n.y + 5, class: "dc-node-t tree-el" }, tree);
        t.textContent = n.v;
      });
      levels.push(next);
      prev = next;
    }
    const root = prev[0];
    const treeLabel = svg("text", { x: 18, y: 296, class: "dc-label tree-el" }, tree);
    treeLabel.textContent = "width-7 adder tree";

    // Comparator + output.
    const cmp = svg("g", { opacity: 0, style: "transition:opacity .5s" }, S);
    const cx = root.x + 150;
    svg("path", { d: `M${root.x + 26} ${root.y} H${cx - 40}`, class: "dc-edge vis" }, cmp);
    svg("rect", { x: cx - 40, y: root.y - 26, width: 110, height: 52, rx: 10, class: "dc-cmp" }, cmp);
    const ct = svg("text", { x: cx + 15, y: root.y + 6, class: "dc-node-t vis" }, cmp);
    ct.textContent = `≥ θ = ${THETA}`;
    svg("path", { d: `M${cx + 70} ${root.y} H${cx + 110}`, class: "dc-edge vis" }, cmp);
    const yLed = svg("circle", { cx: cx + 124, cy: root.y, r: 14, class: "dc-y" }, cmp);
    const yT = svg("text", { x: cx + 124, y: root.y + 42, class: "dc-label", "text-anchor": "middle" }, cmp);
    yT.textContent = "y";
    const foot = svg("text", { x: 450, y: 448, class: "dc-label", "text-anchor": "middle", opacity: 0, style: "transition:opacity .5s" }, S);
    foot.textContent = "sky130_fd_sc_hd standard cells only: muxes, AOI cells, adders";

    const total = bits.reduce((a, b) => a + b, 0);
    scrollyHandlers.decomp = (s) => {
      fan.style.opacity = s === 0 ? 1 : 0;
      fan.style.transition = "opacity .5s";
      bitEls.forEach((el, i) => (el.style.transform = s === 0 ? "translate(0px,0px)" : `translate(${(groupedX(i) - rowX(i)).toFixed(1)}px,0px)`));
      chunkRects.forEach((r) => r.style.opacity = s >= 1 ? 1 : 0);
      countT.forEach((t) => t.style.opacity = s >= 2 ? 1 : 0);
      lutT.forEach((t) => t.style.opacity = s >= 2 ? .8 : 0);
      $$(".tree-el", tree).forEach((el) => el.style.opacity = s >= 3 ? 1 : 0);
      cmp.setAttribute("opacity", s >= 4 ? 1 : 0);
      foot.setAttribute("opacity", s >= 2 ? 1 : 0);
      yLed.classList.toggle("on", s >= 4 && total >= THETA);
      topLabel.textContent = s === 0 ? "64 XNOR bits (x XNOR w)" : "10 × 6-bit chunks + 1 × 4-bit residue";
    };
  })();

  /* ------------------------------------------------------------------ */
  /* 04: tile lanes                                                      */
  /* ------------------------------------------------------------------ */
  (function tile() {
    const host = $("#ta-lanes");
    if (!host) return;
    const rand = rng(9);
    for (let i = 0; i < 16; i++) {
      const d = document.createElement("div");
      d.className = "lane";
      d.style.setProperty("--d", (rand() * 0.25).toFixed(2) + "s");
      host.appendChild(d);
    }
    // y register: a new 16-bit answer every pipeline round
    const yb = $("#ta-ybits");
    const ys = Array.from({ length: 16 }, () => { const i = document.createElement("i"); yb.appendChild(i); return i; });
    const flip = () => ys.forEach((i) => i.classList.toggle("on", rand() > .5));
    flip();
    if (!REDUCED) $("#tile-anim").addEventListener("revealed", () => setInterval(flip, 2400), { once: true });
  })();

  /* ------------------------------------------------------------------ */
  /* 05: SoC bus transactions                                            */
  /* ------------------------------------------------------------------ */
  (function soc() {
    const S = $("#soc-svg");
    if (!S) return;
    const layer = $("#soc-packets");
    const ROUTES = {
      imem: [[230, 260], [265, 260], [265, 128]],
      dmem: [[230, 260], [635, 260], [635, 128]],
      tile: [[230, 260], [450, 260], [450, 398]],
      gpio: [[230, 260], [730, 260], [730, 398]],
    };
    const BLK = { imem: "#b-imem", dmem: "#b-dmem", tile: "#b-tile", gpio: "#b-gpio" };
    const WIRE = { imem: "#w-imem", dmem: "#w-dmem", tile: "#w-tile", gpio: "#w-gpio" };
    let token = 0;

    function len(pts) { let L = 0; for (let i = 1; i < pts.length; i++) L += Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]); return L; }
    function at(pts, d) {
      for (let i = 1; i < pts.length; i++) {
        const seg = Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]);
        if (d <= seg) { const k = d / seg; return [pts[i - 1][0] + (pts[i][0] - pts[i - 1][0]) * k, pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * k]; }
        d -= seg;
      }
      return pts[pts.length - 1];
    }
    function move(target, label, back, my) {
      return new Promise((resolve) => {
        if (my !== token) return resolve();
        let pts = ROUTES[target];
        if (back) pts = pts.slice().reverse();
        const L = len(pts), dur = L * 2.2;
        const dot = svg("circle", { r: 7, class: "packet" }, layer);
        const txt = svg("text", { class: "packet-t" }, layer);
        txt.textContent = label;
        $(WIRE[target]).classList.add("lit"); $("#w-cpu").classList.add("lit");
        const t0 = performance.now();
        (function frame(now) {
          const k = Math.min(1, (now - t0) / dur);
          const [x, y] = at(pts, k * L);
          dot.setAttribute("cx", x); dot.setAttribute("cy", y);
          txt.setAttribute("x", x + 11); txt.setAttribute("y", y - 9);
          if (k < 1 && my === token) requestAnimationFrame(frame);
          else { dot.remove(); txt.remove(); resolve(); }
        })(t0);
      });
    }
    function lit(targets) {
      Object.values(BLK).forEach((b) => $(b).classList.remove("lit"));
      $("#b-cpu").classList.remove("lit");
      $$(".wire", S).forEach((w) => w.classList.remove("lit"));
      targets.forEach((t) => $(t === "cpu" ? "#b-cpu" : BLK[t]).classList.add("lit"));
    }
    const CAPS = [
      ["soc_top", "1 master · 4 slaves<br>adr[31:28] decode<br>single clock, 100 MHz"],
      ["BOOT", "PROGADDR_RESET = 0<br>fetch RV32I from IMEM"],
      ["CONFIG", "W[i] ← LO, HI (64 b)<br>θ[i] ← 7 b<br>×16 neurons"],
      ["INFER", "x ← DMEM<br>X_LO, X_HI → tile<br>HI write starts eval"],
      ["HANDSHAKE", "poll STATUS.BUSY<br>read YOUT (16 b)<br>write CTRL.CLR_DONE"],
      ["PER IMAGE", "4 tile evals (layer 1)<br>layer 2 on the CPU<br><b id='cyc'>0</b> cycles"],
    ];
    function caption(s) {
      $("#soc-cap-h").textContent = CAPS[s][0];
      $("#soc-cap-b").innerHTML = CAPS[s][1];
    }
    const SEQ = {
      1: [["imem", "fetch"], ["imem", "instr", 1]],
      2: [["imem", "lw w"], ["imem", "w", 1], ["tile", "W LO"], ["tile", "W HI"], ["tile", "θ"]],
      3: [["dmem", "lw x"], ["dmem", "x", 1], ["tile", "X LO"], ["tile", "X HI"]],
      4: [["tile", "BUSY?"], ["tile", "1", 1], ["tile", "BUSY?"], ["tile", "0", 1], ["tile", "YOUT?"], ["tile", "y[15:0]", 1], ["tile", "CLR"]],
      5: [["tile", "eval 1"], ["tile", "eval 2"], ["tile", "eval 3"], ["tile", "eval 4"]],
    };
    async function run(s, my) {
      const litMap = { 0: ["tile"], 1: ["cpu", "imem"], 2: ["cpu", "tile"], 3: ["cpu", "dmem", "tile"], 4: ["cpu", "tile"], 5: ["cpu", "tile"] };
      lit(litMap[s]);
      caption(s);
      if (s === 5) {
        const el = $("#cyc");
        tween(0, 17068, REDUCED ? 0 : 2600, (v) => { if (el) el.textContent = Math.round(v).toLocaleString("en-US"); });
      }
      if (REDUCED || !SEQ[s]) return;
      while (my === token) {
        for (const [t, label, back] of SEQ[s]) {
          if (my !== token) return;
          await move(t, label, back, my);
        }
        if (s === 5 && my === token) { $("#b-cpu").classList.add("lit"); await sleep(900); }
        await sleep(400);
      }
    }
    let visible = false, cur = 0;
    new IntersectionObserver(([e]) => {
      visible = e.isIntersecting; token++;
      if (visible) run(cur, token);
    }).observe(S);
    scrollyHandlers.soc = (s) => { cur = s; token++; layer.innerHTML = ""; if (visible || s === 0) run(s, token); };
  })();

  /* ------------------------------------------------------------------ */
  /* 06: the live network                                                */
  /* ------------------------------------------------------------------ */
  (function lab() {
    const pad = $("#pad");
    if (!pad || !window.TinkerBNN) return;
    const B = window.TinkerBNN;
    const pctx = pad.getContext("2d");
    let model = null, samples = null, labels = null, curLabel = null;

    // Build static DOM for the pipeline.
    const quadHost = $("#quads");
    const quadCells = [0, 1, 2, 3].map((k) => {
      const q = document.createElement("div"); q.className = "quad";
      q.title = ["top-left", "top-right", "bottom-left", "bottom-right"][k] + " quadrant";
      const cells = Array.from({ length: 49 }, () => { const i = document.createElement("i"); q.appendChild(i); return i; });
      quadHost.appendChild(q);
      return { q, cells };
    });
    const hidHost = $("#hidden");
    const hidCells = [];
    for (let k = 0; k < 4; k++) {
      const blk = document.createElement("div"); blk.className = "evalblk";
      blk.innerHTML = `<b>eval ${k + 1} · quadrant ${k}</b>`;
      const hb = document.createElement("div"); hb.className = "hb";
      for (let j = 0; j < 16; j++) { const i = document.createElement("i"); hb.appendChild(i); hidCells.push(i); }
      blk.appendChild(hb); hidHost.appendChild(blk);
    }
    const lgHost = $("#logits");
    const lgEls = Array.from({ length: 10 }, (_, c) => {
      const d = document.createElement("div"); d.className = "lg";
      d.innerHTML = `<small>0</small><div class="bar"></div><span>${c}</span>`;
      lgHost.appendChild(d); return d;
    });
    const c14 = $("#c14").getContext("2d");

    function clearPad() {
      pctx.fillStyle = "#0B1424"; pctx.fillRect(0, 0, 280, 280);
      curLabel = null;
      quadCells.forEach(({ cells }) => cells.forEach((c) => c.classList.remove("on")));
      hidCells.forEach((c) => c.classList.remove("on"));
      lgEls.forEach((d) => { d.classList.remove("win"); $(".bar", d).style.height = "0"; $("small", d).textContent = ""; });
      c14.clearRect(0, 0, 140, 140);
      $("#pred").textContent = "–"; $("#pred-sub").textContent = "prediction";
    }

    // MNIST-style preprocessing for a hand drawing.
    function drawingTo28() {
      const src = pctx.getImageData(0, 0, 280, 280).data;
      let x0 = 280, y0 = 280, x1 = -1, y1 = -1;
      for (let y = 0; y < 280; y++) for (let x = 0; x < 280; x++)
        if (src[(y * 280 + x) * 4] > 40) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
      if (x1 < 0) return null;
      const bw = x1 - x0 + 1, bh = y1 - y0 + 1, s = 20 / Math.max(bw, bh);
      const tw = Math.max(1, Math.round(bw * s)), th = Math.max(1, Math.round(bh * s));
      // two-stage downscale for smoother anti-aliasing
      const mid = document.createElement("canvas"); mid.width = tw * 4; mid.height = th * 4;
      const m = mid.getContext("2d"); m.imageSmoothingQuality = "high";
      m.drawImage(pad, x0, y0, bw, bh, 0, 0, mid.width, mid.height);
      const small = document.createElement("canvas"); small.width = tw; small.height = th;
      const sm = small.getContext("2d"); sm.imageSmoothingQuality = "high";
      sm.drawImage(mid, 0, 0, tw, th);
      const sd = sm.getImageData(0, 0, tw, th).data;
      // center of mass → (14,14)
      let mx = 0, my = 0, mass = 0;
      for (let y = 0; y < th; y++) for (let x = 0; x < tw; x++) { const v = sd[(y * tw + x) * 4]; mx += x * v; my += y * v; mass += v; }
      const ox = Math.round(14 - mx / mass), oy = Math.round(14 - my / mass);
      const out = new Uint8Array(784);
      for (let y = 0; y < th; y++) for (let x = 0; x < tw; x++) {
        const X = x + ox, Y = y + oy;
        if (X >= 0 && X < 28 && Y >= 0 && Y < 28) out[Y * 28 + X] = sd[(y * tw + x) * 4];
      }
      return out;
    }

    let runId = 0;
    async function show(img, animate) {
      const my = ++runId;
      const r = B.forward(img, model);
      const step = animate && !REDUCED ? 1 : 0;
      // ① pooled image
      const id = c14.createImageData(14, 14);
      for (let i = 0; i < 196; i++) { const v = Math.round(r.p14[i] / 1020 * 255); id.data.set([v, v, v, 255], i * 4); }
      const tmp = document.createElement("canvas"); tmp.width = 14; tmp.height = 14; tmp.getContext("2d").putImageData(id, 0, 0);
      c14.imageSmoothingEnabled = false; c14.clearRect(0, 0, 140, 140); c14.drawImage(tmp, 0, 0, 140, 140);
      // ② quadrants
      r.quads.forEach((q, k) => q.forEach((b, i) => quadCells[k].cells[i].classList.toggle("on", !!b)));
      // ③ tile evaluations
      if (step) hidCells.forEach((c) => c.classList.remove("on"));
      for (let k = 0; k < 4; k++) {
        if (my !== runId) return;
        quadCells.forEach((q, i) => q.q.classList.toggle("active", step && i === k));
        for (let j = 0; j < 16; j++) hidCells[16 * k + j].classList.toggle("on", !!r.hidden[16 * k + j]);
        if (step) await sleep(260);
      }
      quadCells.forEach((q) => q.q.classList.remove("active"));
      if (my !== runId) return;
      // ④ logits
      const lo = Math.min(...r.logits), hi = Math.max(...r.logits);
      lgEls.forEach((d, c) => {
        const h = hi === lo ? 50 : 8 + 92 * (r.logits[c] - lo) / (hi - lo);
        $(".bar", d).style.height = h + "%";
        $("small", d).textContent = r.logits[c];
        d.classList.toggle("win", c === r.pred);
      });
      if (step) await sleep(250);
      if (my !== runId) return;
      $("#pred").textContent = r.pred;
      $("#pred-sub").textContent = curLabel === null ? "prediction" :
        (curLabel === r.pred ? `test label ${curLabel} ✓` : `test label ${curLabel} ✗`);
    }

    // Drawing.
    let drawing = false, last = null, dirty = false;
    function pos(e) { const b = pad.getBoundingClientRect(); return [(e.clientX - b.left) * 280 / b.width, (e.clientY - b.top) * 280 / b.height]; }
    pad.addEventListener("pointerdown", (e) => {
      if (curLabel !== null) clearPad();
      drawing = true; last = pos(e); pad.setPointerCapture(e.pointerId); stroke(last, last);
    });
    pad.addEventListener("pointermove", (e) => { if (!drawing) return; const p = pos(e); stroke(last, p); last = p; });
    const end = () => { if (!drawing) return; drawing = false; live(true); };
    pad.addEventListener("pointerup", end); pad.addEventListener("pointercancel", end);
    function stroke(a, b) {
      pctx.strokeStyle = "#fff"; pctx.lineWidth = 20; pctx.lineCap = "round"; pctx.lineJoin = "round";
      pctx.beginPath(); pctx.moveTo(a[0], a[1]); pctx.lineTo(b[0], b[1]); pctx.stroke();
      if (!dirty) { dirty = true; requestAnimationFrame(() => { dirty = false; live(false); }); }
    }
    function live(animate) { if (!model) return; const img = drawingTo28(); if (img) show(img, animate); }

    function sample() {
      if (!samples) return;
      const i = Math.floor(Math.random() * labels.length);
      const img = samples.subarray(i * 784, (i + 1) * 784);
      const tmp = document.createElement("canvas"); tmp.width = 28; tmp.height = 28;
      const t = tmp.getContext("2d"), id = t.createImageData(28, 28);
      for (let k = 0; k < 784; k++) id.data.set([img[k], img[k], img[k], 255], k * 4);
      t.putImageData(id, 0, 0);
      clearPad();
      pctx.imageSmoothingEnabled = false; pctx.drawImage(tmp, 0, 0, 280, 280);
      curLabel = labels[i];
      show(img, true);   // raw MNIST pixels: bit-exact with the golden model
    }

    $("#pad-clear").addEventListener("click", clearPad);
    $("#pad-sample").addEventListener("click", sample);
    clearPad();

    fetch("model.json").then((r) => r.json()).then((j) => {
      model = B.parseModel(j);
      const bin = atob(j.samples.images_b64);
      samples = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) samples[i] = bin.charCodeAt(i);
      labels = j.samples.labels;
      const sec = $("#try");
      new IntersectionObserver(([e], io) => { if (e.isIntersecting) { sample(); io.disconnect(); } }, { threshold: .3 }).observe(sec);
    }).catch(() => { $("#pad-hint").textContent = "Could not load model.json. Serve this folder over HTTP to run the demo."; });
  })();

  /* ------------------------------------------------------------------ */
  /* 08: power                                                           */
  /* ------------------------------------------------------------------ */
  (function power() {
    const barEl = $("#pw-bar");
    if (!barEl) return;
    const ORDER = ["Clock", "Tile", "CPU", "IMEM", "DMEM", "Shared", "GPIO", "Other"];
    const COLOR = { Clock: "var(--navy)", Tile: "var(--tile)", CPU: "var(--navy-2)", IMEM: "var(--navy-3)", DMEM: "var(--navy-4)", Shared: "var(--navy-5)", GPIO: "#9AA4B2", Other: "#C9CFD8" };
    // Same numbers as paper/figures/fig4_power_breakdown.py (mW, max_ff_n40C_1v95).
    const BASE = { Clock: 42.98, Tile: 11.47, CPU: 7.78, IMEM: 0, DMEM: 38.58, Shared: 0, GPIO: 0.30, Other: 4.95 };
    const ORAM = { Clock: 15.10, Tile: 11.47, CPU: 7.71, IMEM: 5.56, DMEM: 3.85, Shared: 1.24, GPIO: 0.30, Other: 1.98 };
    const MAX = 106.06;
    const segs = {};
    ORDER.forEach((k) => {
      const s = document.createElement("div");
      s.className = "pw-seg" + (k === "Tile" ? " tile" : "");
      s.style.background = COLOR[k]; s.title = k;
      barEl.appendChild(s); segs[k] = s;
    });
    $("#pw-legend").innerHTML = ORDER.map((k) => `<span><i style="background:${COLOR[k]}"></i>${k}</span>`).join("");
    const C = 2 * Math.PI * 50;
    let shown = { total: 106.06, share: 10.8 };
    function set(data, total, share, label) {
      ORDER.forEach((k) => (segs[k].style.flexBasis = (data[k] / MAX * 100) + "%"));
      ORDER.forEach((k) => (segs[k].title = `${k}: ${data[k].toFixed(2)} mW`));
      $("#pw-label").textContent = label;
      const f = shown;
      tween(f.total, total, 1100, (v) => ($("#pw-total").textContent = v.toFixed(2)));
      tween(f.share, share, 1100, (v) => {
        $("#pw-share").textContent = v.toFixed(1);
        $("#pw-ring").style.strokeDashoffset = C * (1 - v / 100);
      });
      shown = { total, share };
    }
    scrollyHandlers.power = (s) => {
      if (s === 0) set(BASE, 106.06, 10.8, "register-file IMEM / DMEM (baseline)");
      else set(ORAM, 47.21, 24.3, "OpenRAM IMEM / DMEM macros (TINKER)");
    };
  })();

  /* ------------------------------------------------------------------ */
  /* BibTeX copy                                                         */
  /* ------------------------------------------------------------------ */
  $("#copy-bib")?.addEventListener("click", async (e) => {
    try { await navigator.clipboard.writeText($(".bib code").textContent); e.target.textContent = "Copied ✓"; }
    catch { e.target.textContent = "Select and copy above"; }
    setTimeout(() => (e.target.textContent = "Copy BibTeX"), 1800);
  });

  initScrolly();
})();
