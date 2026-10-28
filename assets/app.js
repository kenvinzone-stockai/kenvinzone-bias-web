/* KenvinZone Market Bias Terminal — Phase 1 (vanilla JS, no build step).
 * Reads data/latest.json (Schema v1.0, produced by
 * market-bias-platform/scripts/export_web_json.py).
 *
 * HARD RULE: the frontend never re-classifies a score. `regime` comes from
 * the engine; thresholds come from payload.regimeThresholds (used only to
 * draw bands and label ranges).
 */
(() => {
  "use strict";

  // ── Config (edit here, not inline) ────────────────────────────────────────
  const CONFIG = {
    dataUrl: "data/latest.json",
    links: {
      telegram: "https://t.me/kenvinzone",
      waitlist: "https://kenvinzone.com/library/paths/master-aurora-standard/",
    },
    decks: {
      vi: "decks/aurora-explainer-bias-reading/index.html",
      en: "decks/aurora-explainer-bias-reading-en/index.html",
    },
    assetOrder: ["GOLD", "SPX", "NASDAQ"],
    // Display-only gauge compression: |score| <= knee fills `kneeShare` of
    // each half-arc. Tick labels always show true values.
    gauge: { knee: 35, kneeShare: 0.75 },
  };

  // ── Regime dictionary (5 engine regimes + insufficient data) ──────────────
  const REGIMES = {
    "Strong Bullish": {
      key: "sbull", vi: "Tăng mạnh", color: "var(--r-sbull)",
      playbook: "Ưu tiên setup BUY của AURORA khi giá hồi về hỗ trợ / Put Wall. Không Sell chặn đầu xu hướng.",
      gamma: "Giá hồi về gần Put Wall hoặc giữ trên Gamma Flip",
      action: "Chờ AURORA kích hoạt Buy M15/H1, trailing ATR, rủi ro cố định 1R.",
    },
    "Bullish": {
      key: "bull", vi: "Thiên tăng", color: "var(--r-bull)",
      playbook: "Thiên về BUY với khối lượng tiêu chuẩn. Chỉ vào lệnh khi AURORA xác nhận, bỏ qua tín hiệu Sell ngược chiều.",
      gamma: "Giá trên Gamma Flip, chưa chạm Call Wall",
      action: "Buy theo xác nhận AURORA, chốt từng phần khi tiệm cận Call Wall.",
    },
    "Neutral": {
      key: "neutral", vi: "Trung tính", color: "var(--r-neutral)",
      playbook: "Dòng tiền giằng co: giảm ~50% khối lượng, scalp trong biên Put Wall – Call Wall, không đánh breakout, không giữ lệnh qua đêm.",
      gamma: "Giá kẹp giữa Put Wall và Call Wall",
      action: "Scalp đảo chiều tại biên, chốt lời nhanh, đứng ngoài nếu AURORA không rõ màu.",
    },
    "Bearish": {
      key: "bear", vi: "Thiên giảm", color: "var(--r-bear)",
      playbook: "Thiên về SELL với khối lượng tiêu chuẩn. Không bắt đáy; chỉ vào lệnh khi AURORA xác nhận.",
      gamma: "Giá dưới Gamma Flip, chưa chạm Put Wall",
      action: "Sell theo xác nhận AURORA, chốt từng phần khi tiệm cận Put Wall.",
    },
    "Strong Bearish": {
      key: "sbear", vi: "Giảm mạnh", color: "var(--r-sbear)",
      playbook: "Ưu tiên setup SELL của AURORA khi giá hồi lên kháng cự / Call Wall. Tuyệt đối không bắt đáy.",
      gamma: "Giá hồi lên gần Call Wall hoặc dưới Gamma Flip",
      action: "Chờ AURORA kích hoạt Sell M15/H1, trailing ATR, rủi ro cố định 1R.",
    },
    "Insufficient Data": {
      key: "na", vi: "Thiếu dữ liệu", color: "var(--r-na)",
      playbook: "Engine chưa đủ dữ liệu để chấm điểm. Đứng ngoài hoặc chỉ dùng khung thời gian khác.",
      gamma: "—", action: "—",
    },
  };
  const MATRIX_ORDER = ["Strong Bullish", "Bullish", "Neutral", "Bearish", "Strong Bearish"];

  const CATEGORY_VI = {
    liquidity: "Thanh khoản Fed", rates: "Lãi suất & Lạm phát", usd: "Sức mạnh USD",
    risk: "Tâm lý rủi ro", breadth: "Độ rộng thị trường", options: "Quyền chọn / Gamma",
    positioning: "Vị thế CFTC COT", flows: "Dòng tiền ETF", gold_specific: "Đặc thù Vàng",
    seasonality: "Mùa vụ", technical: "Kỹ thuật",
  };
  const DRIVER_VI = {
    us_m2: "Cung tiền M2", us_10y_real_yield: "Lợi suất thực 10Y", us_5y_real_yield: "Lợi suất thực 5Y",
    usd_directional_pressure: "Áp lực USD", move_index: "MOVE Index", hy_oas: "HY OAS spread",
    cot_gold_trend: "COT Vàng", gold_silver_ratio: "Tỷ lệ Vàng/Bạc", copper_gold_ratio: "Tỷ lệ Đồng/Vàng",
    gold_spx_divergence: "Phân kỳ Vàng–SPX", vix: "VIX", net_liquidity: "Net Liquidity",
  };

  // ── State ─────────────────────────────────────────────────────────────────
  const state = { data: null, asset: "GOLD", tf: "weekly", lang: "vi" };
  const $ = (id) => document.getElementById(id);

  // ── Formatting ────────────────────────────────────────────────────────────
  const fmtScore = (v) => (v == null ? "—" : (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(1));
  const fmtNum = (v, d = 2) => (v == null ? "—" : Number(v).toLocaleString("en-US", { maximumFractionDigits: d }));
  const fmtPct = (v) => (v == null ? "—" : Math.round(v * 100) + "%");
  const fmtDate = (iso) => {
    if (!iso) return "—";
    const [y, m, d] = iso.slice(0, 10).split("-");
    return `${d}/${m}/${y}`;
  };
  const humanize = (k) => (DRIVER_VI[k] || CATEGORY_VI[k] || String(k || "").replace(/_/g, " "));
  const regimeOf = (name) => REGIMES[name] || REGIMES["Insufficient Data"];

  // Age in hours of a YYYY-MM-DD date (treated as end of that day, UTC+7).
  function ageHours(isoDate) {
    if (!isoDate) return Infinity;
    const end = new Date(isoDate.slice(0, 10) + "T23:59:59+07:00");
    return (Date.now() - end.getTime()) / 36e5;
  }

  // ── Gauge geometry ────────────────────────────────────────────────────────
  const CX = 160, CY = 160, R = 118;
  function gaugeFrac(s) {
    const { knee, kneeShare } = CONFIG.gauge;
    const a = Math.min(Math.abs(s), 100);
    const f = a <= knee ? (a / knee) * kneeShare : kneeShare + ((a - knee) / (100 - knee)) * (1 - kneeShare);
    return Math.sign(s) * f; // -1 … +1
  }
  const angleOf = (s) => gaugeFrac(s) * 90; // degrees from vertical
  function pt(deg, r) {
    const t = (deg * Math.PI) / 180;
    return [CX + r * Math.sin(t), CY - r * Math.cos(t)];
  }
  function arc(s0, s1, r) {
    const [x0, y0] = pt(angleOf(s0), r), [x1, y1] = pt(angleOf(s1), r);
    const large = Math.abs(angleOf(s1) - angleOf(s0)) > 180 ? 1 : 0;
    return `M${x0.toFixed(2)} ${y0.toFixed(2)} A${r} ${r} 0 ${large} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
  }
  const svgEl = (tag, attrs) => {
    const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const k in attrs) el.setAttribute(k, attrs[k]);
    return el;
  };

  function drawGaugeFrame(th) {
    const bands = $("gauge-bands"), ticks = $("gauge-ticks");
    bands.innerHTML = ""; ticks.innerHTML = "";
    const segs = [
      [-100, th.strongBearishMax, "var(--r-sbear)"],
      [th.strongBearishMax, th.bearishMax, "var(--r-bear)"],
      [th.bearishMax, th.bullishMin, "var(--r-neutral)"],
      [th.bullishMin, th.strongBullishMin, "var(--r-bull)"],
      [th.strongBullishMin, 100, "var(--r-sbull)"],
    ];
    bands.appendChild(svgEl("path", { d: arc(-100, 100, R), class: "band band-bg" }));
    for (const [a, b, c] of segs) {
      bands.appendChild(svgEl("path", { d: arc(a, b, R), class: "band", stroke: c, "stroke-opacity": ".85" }));
    }
    const marks = [-100, -CONFIG.gauge.knee, th.strongBearishMax, th.bearishMax, 0,
                   th.bullishMin, th.strongBullishMin, CONFIG.gauge.knee, 100];
    for (const m of [...new Set(marks)]) {
      const deg = angleOf(m);
      const [x0, y0] = pt(deg, R - 9), [x1, y1] = pt(deg, R + 9);
      ticks.appendChild(svgEl("line", { x1: x0, y1: y0, x2: x1, y2: y1, class: "tick" }));
      const [lx, ly] = pt(deg, R + 24);
      const t = svgEl("text", { x: lx, y: ly + 3, class: "tick-label" });
      t.textContent = m > 0 ? "+" + m : String(m);
      ticks.appendChild(t);
    }
  }

  // ── Renderers ─────────────────────────────────────────────────────────────
  function renderTabs() {
    const nav = $("asset-tabs");
    nav.innerHTML = "";
    for (const key of CONFIG.assetOrder) {
      const a = state.data.assets[key];
      if (!a) continue;
      const w = a[state.tf];
      const b = document.createElement("button");
      b.className = "asset-tab";
      b.setAttribute("role", "tab");
      b.setAttribute("aria-selected", String(key === state.asset));
      b.innerHTML = `<span>${a.label}</span><span class="mini" style="color:${regimeOf(w && w.regime).color}">${fmtScore(w && w.score)}</span>`;
      b.addEventListener("click", () => { state.asset = key; syncHash(); renderAll(); });
      nav.appendChild(b);
    }
  }

  function renderGauge() {
    const a = state.data.assets[state.asset];
    const b = a[state.tf];
    const r = regimeOf(b && b.regime);
    document.documentElement.style.setProperty("--accent", r.color);
    $("tf-label").textContent = state.tf === "weekly" ? "khung Tuần" : "khung Ngày";
    $("score").textContent = fmtScore(b && b.score);
    $("regime-pill").textContent = r.vi;
    $("playbook-text").textContent = r.playbook;
    const deg = b && b.score != null ? angleOf(b.score) : 0;
    $("gauge-needle").style.transform = `rotate(${deg}deg)`;
    $("score-change").textContent = b && b.scoreChange != null ? fmtScore(b.scoreChange) : "—";
    $("coverage").textContent = fmtPct(b && b.dataCoverage);
    $("asof").textContent = fmtDate(b && b.asOf);
    document.querySelectorAll(".zone-gauge .seg button").forEach((btn) =>
      btn.setAttribute("aria-selected", String(btn.dataset.tf === state.tf)));
  }

  function renderDivergence() {
    const a = state.data.assets[state.asset];
    const rows = [["Tuần", a.weekly], ["Ngày", a.daily]];
    $("dv-bars").innerHTML = rows.map(([lbl, b]) => {
      const r = regimeOf(b && b.regime);
      const f = gaugeFrac((b && b.score) || 0) * 50;
      const left = f >= 0 ? 50 : 50 + f;
      return `<div class="dv-row"><span>${lbl}</span>
        <div class="track"><div class="fill" style="left:${left}%;width:${Math.abs(f)}%;background:${r.color}"></div></div>
        <span class="val" style="color:${r.color}">${fmtScore(b && b.score)}</span></div>`;
    }).join("");
    const d = a.divergence || {};
    const tag = $("dv-status");
    if (d.status === "DIVERGENCE") {
      tag.textContent = "Lệch pha"; tag.className = "tag warn";
      const wUp = d.weeklyScore > 0;
      $("dv-note").textContent = wUp
        ? "Tuần nghiêng tăng nhưng Ngày đang chịu áp lực giảm: không FOMO Buy đuổi, chờ giá kiểm định hỗ trợ rồi mới theo sóng tuần."
        : "Tuần nghiêng giảm nhưng Ngày đang hồi: không bắt đáy theo nhịp hồi, chờ giá chạm kháng cự để theo sóng tuần.";
    } else if (d.status === "ALIGNED") {
      tag.textContent = "Đồng pha"; tag.className = "tag ok";
      $("dv-note").textContent = "Tuần và Ngày cùng chiều: ưu tiên tín hiệu AURORA thuận theo hướng chung.";
    } else {
      tag.textContent = "Chưa đủ dữ liệu"; tag.className = "tag";
      $("dv-note").textContent = "Chưa đủ dữ liệu hai khung để so sánh.";
    }
  }

  function renderDrivers() {
    const b = state.data.assets[state.asset][state.tf];
    const cats = (b && b.categories) || [];
    const maxAbs = Math.max(1, ...cats.map((c) => Math.abs(c.contribution || 0)));
    $("cat-list").innerHTML = cats.length ? cats.map((c) => {
      const v = c.contribution || 0;
      const w = (Math.abs(v) / maxAbs) * 50;
      const col = v >= 0 ? "var(--r-sbull)" : "var(--r-sbear)";
      return `<li title="Trọng số ${fmtPct(c.weight)} · điểm thô ${fmtScore(c.rawScore)}">
        <span class="name">${humanize(c.key)}</span>
        <div class="track"><div class="fill" style="left:${v >= 0 ? 50 : 50 - w}%;width:${w}%;background:${col}"></div></div>
        <span class="val" style="color:${col}">${fmtScore(v)}</span></li>`;
    }).join("") : `<li class="muted">Chưa có dữ liệu trụ cột.</li>`;
    const li = (arr) => (arr || []).slice(0, 3).map((d) => `<li>${humanize(d.name)} <b>${fmtScore(d.contribution)}</b></li>`).join("") || "<li>—</li>";
    $("top-pos").innerHTML = li(b && b.topPositive);
    $("top-neg").innerHTML = li(b && b.topNegative);
  }

  function renderMatrix() {
    const th = state.data.regimeThresholds;
    const b = state.data.assets[state.asset][state.tf];
    const current = b && b.regime;
    const ranges = {
      "Strong Bullish": `≥ +${th.strongBullishMin}`,
      "Bullish": `+${th.bullishMin} → +${th.strongBullishMin}`,
      "Neutral": `${th.bearishMax} → +${th.bullishMin}`,
      "Bearish": `${th.strongBearishMax} → ${th.bearishMax}`,
      "Strong Bearish": `≤ ${th.strongBearishMax}`,
    };
    $("matrix").innerHTML = MATRIX_ORDER.map((name) => {
      const r = REGIMES[name];
      const on = name === current;
      return `<div class="mrow${on ? " active" : ""}" role="row" style="--row-c:${r.color}">
        <div class="m-head"><span class="m-regime">${r.vi}${on ? '<span class="now">Đang áp dụng</span>' : ""}</span><span class="m-range">${ranges[name]}</span></div>
        <div class="m-gamma">${r.gamma}</div>
        <div class="m-action">${r.action}</div></div>`;
    }).join("");
  }

  function renderGamma() {
    const a = state.data.assets[state.asset];
    const g = a.gamma || {};
    $("gamma-und").textContent = g.underlying || "—";
    const tag = $("gamma-regime");
    const body = $("gamma-body");
    if (g.putWall == null || g.callWall == null) {
      tag.textContent = "Chưa có dữ liệu"; tag.className = "tag";
      body.innerHTML = `<div class="empty"><b>Chưa có snapshot options cho ${g.underlying || "tài sản này"}</b>
        Các mốc sẽ hiển thị khi engine cập nhật dữ liệu quyền chọn trước phiên Âu/Mỹ.</div>
        <ul class="glossary">
          <li style="--c:var(--r-sbull)"><span><b>Put Wall</b>: mức có nhiều hợp đồng Put nhất, thường đóng vai trò hỗ trợ.</span></li>
          <li style="--c:var(--gold)"><span><b>Gamma Flip</b>: ranh giới giữa vùng biến động êm (trên) và vùng biến động mạnh (dưới).</span></li>
          <li style="--c:var(--r-sbear)"><span><b>Call Wall</b>: mức có nhiều hợp đồng Call nhất, thường đóng vai trò kháng cự.</span></li>
        </ul>`;
      return;
    }
    const stale = ageHours(g.asOf) > state.data.staleAfterHours.gamma;
    if (g.gammaRegime === "positive") { tag.textContent = "Gamma dương: biến động thấp"; tag.className = "tag ok"; }
    else if (g.gammaRegime === "negative") { tag.textContent = "Gamma âm: biến động mạnh"; tag.className = "tag bad"; }
    else { tag.textContent = "—"; tag.className = "tag"; }

    // Quy đổi tương ứng ra mức Giao ngay Spot (XAUUSD / SPX / NDX) cho trader
    const sa = g.spotAsset || null;
    const spotSym = (sa && sa.symbol) || (state.asset === "GOLD" ? "XAUUSD" : (state.asset === "SPX" ? "SPX" : "NDX"));
    
    // Tỷ lệ quy đổi động từ DB hoặc hệ số chuẩn
    let ratio = sa && sa.ratio;
    if (!ratio && g.spot) {
      if (state.asset === "GOLD") {
        ratio = g.spot > 300 ? (4062.0 / 367.82) : 10.85;
      } else if (state.asset === "SPX") {
        ratio = 10.03;
      } else if (state.asset === "NASDAQ") {
        ratio = 41.25;
      }
    }

    const spotPut = (sa && sa.putWall) || (ratio && g.putWall ? Math.round(g.putWall * ratio * 10) / 10 : null);
    const spotCall = (sa && sa.callWall) || (ratio && g.callWall ? Math.round(g.callWall * ratio * 10) / 10 : null);
    const spotFlip = (sa && sa.gammaFlip) || (ratio && g.gammaFlip ? Math.round(g.gammaFlip * ratio * 10) / 10 : null);
    const spotPrice = (sa && sa.spot) || (ratio && g.spot ? Math.round(g.spot * ratio * 10) / 10 : null);

    const pts = [g.putWall, g.callWall, g.gammaFlip, g.spot].filter((v) => v != null);
    let lo = Math.min(...pts), hi = Math.max(...pts);
    const pad = (hi - lo) * 0.12 || 1; lo -= pad; hi += pad;
    const x = (v) => ((v - lo) / (hi - lo)) * 100;

    const lv = (cls, name, v, sv) => {
      if (v == null) return "";
      const sub = sv != null ? `<div class="lv-spot">≈ ${fmtNum(sv, 1)}</div>` : "";
      return `<div class="lv ${cls}" style="left:${x(v)}%">
        ${cls === "spot" ? '<div class="dot"></div>' : ""}
        ${cls !== "spot" 
          ? `<div class="lv-name">${name}</div><div class="lv-val">${fmtNum(v)}</div>${sub}<div class="lv-line"></div>` 
          : `<div class="lv-name">${name} ${fmtNum(v)}</div>${sub}`}
      </div>`;
    };

    const statCard = (k, v, sv, col) => {
      const sub = sv != null ? `<div class="v-spot">≈ <strong>${fmtNum(sv, 1)}</strong> <span class="v-sym">${spotSym}</span></div>` : "";
      return `<div class="g-stat">
        <div class="k">${k}</div>
        <div class="v" style="color:${col}">${fmtNum(v)} <span class="v-unit">${g.underlying}</span></div>
        ${sub}
      </div>`;
    };

    const noteSpot = spotPrice ? ` · Mức quy đổi <strong>${spotSym}</strong> là giá tham chiếu tương đương (1 ${g.underlying} ≈ ${fmtNum(ratio, 2)} ${spotSym}) giúp trader dễ dàng áp dụng mốc cản/hỗ trợ trên biểu đồ MT4/MT5.` : "";

    body.innerHTML = `
      <div class="ladder" aria-label="Thang mốc Gamma">
        <div class="rail"></div>
        ${lv("put", "Put Wall", g.putWall, spotPut)}
        ${lv("flip", "Gamma Flip", g.gammaFlip, spotFlip)}
        ${lv("call", "Call Wall", g.callWall, spotCall)}
        ${lv("spot", "Giá", g.spot, spotPrice)}
      </div>
      <div class="g-stats">
        ${statCard("Put Wall (Hỗ trợ)", g.putWall, spotPut, "var(--r-sbull)")}
        ${statCard("Call Wall (Kháng cự)", g.callWall, spotCall, "var(--r-sbear)")}
        ${statCard("Gamma Flip (Đảo pha)", g.gammaFlip, spotFlip, "var(--gold)")}
        ${statCard(`Giá ${g.underlying}`, g.spot, spotPrice, "var(--cyan)")}
      </div>
      <p class="muted small">Đơn vị gốc: giá ${g.underlying} (ETF)${noteSpot} Dữ liệu ngày ${fmtDate(g.asOf)}${g.source === "manual" ? " · nhập tay" : ""}${stale ? ' · <span style="color:var(--gold)">dữ liệu cũ</span>' : ""}.</p>`;
  }

  function renderStatus() {
    const a = state.data.assets[state.asset];
    const b = a[state.tf];
    const limit = state.data.staleAfterHours[state.tf];
    const el = $("status");
    const stale = ageHours(b && b.asOf) > limit;
    el.classList.toggle("stale", stale);
    el.classList.remove("error");
    $("status-text").textContent = stale
      ? `Dữ liệu cũ, ngày ${fmtDate(b && b.asOf)}`
      : `Dữ liệu ngày ${fmtDate(b && b.asOf)}`;
  }

  function renderFooter() {
    const d = state.data;
    $("fw").textContent = d.frameworkVersion ?? "—";
    $("generated").textContent = d.generatedAt ? d.generatedAt.replace("T", " ").slice(0, 16) : "—";
    if (d.disclaimer && d.disclaimer[state.lang]) $("disclaimer").textContent = d.disclaimer[state.lang];
  }

  function renderAll() {
    renderTabs(); renderGauge(); renderDivergence(); renderDrivers();
    renderMatrix(); renderGamma(); renderHowTo(); renderStatus(); renderFooter();
  }

  // ── Deck player (click-to-load facade, zero layout shift) ─────────────────
  async function loadDeck() {
    const frame = $("deck-frame");
    const url = CONFIG.decks[state.lang];
    try {
      const res = await fetch(url, { method: "HEAD", cache: "no-cache" });
      if (!res.ok) throw new Error(res.status);
    } catch (_) {
      frame.innerHTML = `<div class="empty" style="position:absolute;inset:16px;display:flex;flex-direction:column;justify-content:center">
        <b>Slide chưa được triển khai</b>Copy thư mục deck vào <code>${url.replace("/index.html", "/")}</code></div>`;
      return;
    }
    frame.innerHTML = "";
    const f = document.createElement("iframe");
    f.src = url;
    f.title = "AURORA Explainer — cách đọc Market Bias";
    f.allow = "autoplay; fullscreen";
    f.loading = "lazy";
    frame.appendChild(f);
  }
  function resetDeck() {
    $("deck-frame").innerHTML = `<button class="deck-facade" id="deck-facade" type="button">
      <span class="play" aria-hidden="true"></span><span>${state.lang === "vi" ? "Xem slide giải thích" : "Watch the explainer"}</span>
      <span class="facade-sub">${state.lang === "vi" ? "6 slide · có âm thanh" : "6 slides · with audio"}</span></button>`;
    $("deck-facade").addEventListener("click", loadDeck);
  }

  // ── "How to read" list — numbers come from engine thresholds ─────────────
  function renderHowTo() {
    const el = $("howto");
    if (!el) return;
    const th = state.data.regimeThresholds;
    const isEn = state.lang === "en";
    
    const descEl = $("deck-desc");
    if (descEl) {
      descEl.textContent = isEn
        ? "6-slide framework standardizing quantitative intuition: how to read Bias score, Gamma bounds, and execute with AURORA."
        : "Khung slide 6 bước chuẩn hóa tư duy định lượng: cách đọc điểm Bias kết hợp biên Gamma và kích hoạt lệnh thực chiến với AURORA.";
    }
    const tipEl = $("deck-tip-text");
    if (tipEl) {
      tipEl.innerHTML = isEn
        ? "Click the slide player on the right to walk through candlestick dynamics with <strong>Write You</strong> soundtrack."
        : "Bấm vào khung slide bên phải để xem trực quan từng nến &amp; nghe nhạc nền <strong>Write You</strong>.";
    }

    const items = isEn ? [
      { c: "var(--cyan)", t: "Scale", n: "−100 → +100",
        d: "Positive scores favor buyers; negative favor sellers. Further from zero indicates stronger macro conviction." },
      { c: "var(--r-neutral)", t: "Neutral Range", n: `${th.bearishMax} → +${th.bullishMin}`,
        d: "Conflicting flows, non-directional market. Cut sizing ~50%, scalp Put Wall to Call Wall ranges." },
      { c: "var(--r-sbull)", t: "Strong Trend", n: `from ±${th.strongBullishMin}`,
        d: "Macro pillars aligned. Trade strictly in the direction of Bias with AURORA confirmation." },
    ] : [
      { c: "var(--cyan)", t: "Thang đo", n: "−100 → +100",
        d: "Điểm dương: vĩ mô ủng hộ phe mua. Điểm âm: vĩ mô ủng hộ phe bán. Càng xa 0, lợi thế càng rõ." },
      { c: "var(--r-neutral)", t: "Vùng kẹp", n: `${th.bearishMax} → +${th.bullishMin}`,
        d: "Dòng tiền giằng co, chưa có xu hướng. Giảm khối lượng, đánh biên Put Wall – Call Wall." },
      { c: "var(--r-sbull)", t: "Xu hướng mạnh", n: `từ ±${th.strongBullishMin}`,
        d: "Các trụ cột vĩ mô đồng thuận. Chỉ đánh thuận chiều điểm Bias, không bắt đỉnh đáy." },
    ];
    el.innerHTML = items.map((i) =>
      `<li style="--c:${i.c}"><div><strong>${i.t}<span class="num">${i.n}</span></strong><span>${i.d}</span></div></li>`).join("");
  }

  // ── Theme (dark / light), saved per viewer ────────────────────────────────
  function setTheme(t, save) {
    document.documentElement.setAttribute("data-theme", t);
    if (save) { try { localStorage.setItem("kz-theme", t); } catch (_) {} }
    const btn = $("theme-toggle");
    if (btn) btn.setAttribute("aria-label", t === "dark" ? "Chuyển sang giao diện sáng" : "Chuyển sang giao diện tối");
  }
  function wireTheme() {
    const btn = $("theme-toggle");
    let saved = null;
    try { saved = localStorage.getItem("kz-theme"); } catch (_) {}
    setTheme(saved || document.documentElement.getAttribute("data-theme") || "dark", false);
    if (btn) {
      btn.addEventListener("click", () =>
        setTheme(document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark", true));
    }
    const mq = window.matchMedia && matchMedia("(prefers-color-scheme: light)");
    if (mq && mq.addEventListener) mq.addEventListener("change", (e) => {
      let cur = null; try { cur = localStorage.getItem("kz-theme"); } catch (_) {}
      if (!cur) setTheme(e.matches ? "light" : "dark", false);
    });
  }

  // ── URL hash: #gold-weekly ────────────────────────────────────────────────
  function readHash() {
    const [a, tf] = location.hash.replace("#", "").toUpperCase().split("-");
    if (a && CONFIG.assetOrder.includes(a)) state.asset = a;
    if (tf && ["WEEKLY", "DAILY"].includes(tf)) state.tf = tf.toLowerCase();
  }
  function syncHash() {
    history.replaceState(null, "", `${location.pathname}${location.search}#${state.asset.toLowerCase()}-${state.tf}`);
  }

  // ── Boot ──────────────────────────────────────────────────────────────────
  function wireControls() {
    wireTheme();
    document.querySelectorAll(".zone-gauge .seg button").forEach((btn) =>
      btn.addEventListener("click", () => { state.tf = btn.dataset.tf; syncHash(); renderAll(); }));
    document.querySelectorAll(".zone-deck .seg button").forEach((btn) =>
      btn.addEventListener("click", () => {
        state.lang = btn.dataset.lang;
        document.querySelectorAll(".zone-deck .seg button").forEach((x) =>
          x.setAttribute("aria-selected", String(x === btn)));
        resetDeck();
        renderHowTo();
      }));
    $("deck-facade").addEventListener("click", loadDeck);
    const ctaT = $("cta-telegram"), ctaW = $("cta-waitlist");
    ctaT.href = CONFIG.links.telegram; ctaW.href = CONFIG.links.waitlist;
    window.addEventListener("hashchange", () => { readHash(); renderAll(); });
  }

  async function boot() {
    wireControls();
    readHash();
    try {
      const res = await fetch(CONFIG.dataUrl, { cache: "no-cache" });
      if (!res.ok) throw new Error("HTTP " + res.status);
      const data = await res.json();
      if (!data || data.schemaVersion?.split(".")[0] !== "1") throw new Error("schema " + data?.schemaVersion);
      state.data = data;
      if (!data.assets[state.asset]) state.asset = Object.keys(data.assets)[0];
      drawGaugeFrame(data.regimeThresholds);
      renderAll();
    } catch (err) {
      console.error("[bias] load failed", err);
      $("status").classList.add("error");
      $("status-text").textContent = "Không tải được dữ liệu";
    }
  }

  document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", boot) : boot();
})();
