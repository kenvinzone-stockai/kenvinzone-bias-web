/* ============================================================================
   KENVINZONE MARKET BIAS TERMINAL — MOTION GRAPHIC & SCROLL CRAFT LAYER
   Zero interference with assets/app.js scoring engine.
   Composite-only GPU animations (transform & opacity), 60/120fps.
   ============================================================================ */

(function () {
  const prefersReduced =
    window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------- 1. Top Scroll Telemetry Progress Beam ---------- */
  function initScrollBeam() {
    const beam = document.getElementById("kzScrollBeam");
    if (!beam) return;
    let ticking = false;
    function update() {
      ticking = false;
      const max = Math.max(1, document.documentElement.scrollHeight - window.innerHeight);
      const p = Math.min(1, Math.max(0, window.scrollY / max));
      beam.style.transform = `scaleX(${p.toFixed(4)})`;
    }
    window.addEventListener(
      "scroll",
      () => {
        if (!ticking) {
          ticking = true;
          requestAnimationFrame(update);
        }
      },
      { passive: true }
    );
    update();
  }

  /* ---------- 2. Pointer Spotlight & Subtle 3D Tilt on Tier Cards ---------- */
  function initSpotlights() {
    if (prefersReduced) return;
    document.addEventListener(
      "pointermove",
      (e) => {
        const card = e.target && e.target.closest ? e.target.closest(".card, .tier") : null;
        if (!card) return;
        const r = card.getBoundingClientRect();
        card.style.setProperty("--mx", (e.clientX - r.left).toFixed(1) + "px");
        card.style.setProperty("--my", (e.clientY - r.top).toFixed(1) + "px");
        if (card.classList.contains("tier") && window.innerWidth >= 900) {
          const nx = (e.clientX - r.left) / r.width - 0.5;
          const ny = (e.clientY - r.top) / r.height - 0.5;
          card.style.transform = `perspective(900px) rotateX(${(-ny * 4.5).toFixed(2)}deg) rotateY(${(nx * 5.5).toFixed(2)}deg) translateY(-2px)`;
        }
      },
      { passive: true }
    );

    document.addEventListener(
      "pointerout",
      (e) => {
        const tier = e.target && e.target.closest ? e.target.closest(".tier") : null;
        if (tier && !tier.contains(e.relatedTarget)) tier.style.transform = "";
      },
      { passive: true }
    );
  }

  /* ---------- 3. Ambient Macro Flow Canvas inside Zone 01 Gauge Card ---------- */
  function initGaugeCanvas() {
    const canvas = document.getElementById("kzBiasCanvas");
    if (!canvas || prefersReduced) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let visible = true;
    let rafId = null;
    let phase = 0;

    function resize() {
      const dpr = Math.min(window.devicePixelRatio || 1, 1.75);
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      if (w <= 0 || h <= 0) return;
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    function drawWave(w, h, yFrac, amp, freq, spd, stroke) {
      ctx.beginPath();
      for (let i = 0; i <= 40; i++) {
        const u = i / 40;
        const x = u * w;
        const y =
          yFrac * h +
          Math.sin(u * freq + phase * spd) * amp +
          Math.cos(u * freq * 0.55 - phase * 0.65) * (amp * 0.45);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.strokeStyle = stroke;
      ctx.lineWidth = 1.25;
      ctx.stroke();
    }

    function loop() {
      if (!visible) {
        rafId = null;
        return;
      }
      if (!document.hidden) {
        const w = canvas.clientWidth;
        const h = canvas.clientHeight;
        if (w > 0 && h > 0) {
          ctx.clearRect(0, 0, w, h);
          phase += 0.011;
          drawWave(w, h, 0.28, 16, 4.8, 1.0, "rgba(56, 213, 231, 0.14)");
          drawWave(w, h, 0.55, 20, 3.8, -0.75, "rgba(168, 85, 247, 0.11)");
          drawWave(w, h, 0.78, 14, 5.5, 0.65, "rgba(245, 196, 81, 0.10)");
        }
      }
      rafId = requestAnimationFrame(loop);
    }

    resize();
    window.addEventListener("resize", resize, { passive: true });
    if ("IntersectionObserver" in window) {
      const io = new IntersectionObserver(
        (entries) => {
          visible = entries[0].isIntersecting;
          if (visible && !rafId) loop();
        },
        { threshold: 0.02 }
      );
      io.observe(canvas);
    }
    loop();
  }

  /* ---------- 4. GSAP Scroll Craft Choreography + Score Pop ---------- */
  function initScrollCraft() {
    if (prefersReduced || typeof window.gsap === "undefined") return;
    const gsap = window.gsap;
    if (typeof window.ScrollTrigger !== "undefined") {
      gsap.registerPlugin(window.ScrollTrigger);
    }

    const cards = document.querySelectorAll("main.grid > .card");
    if (cards.length) {
      cards.forEach((card, idx) => {
        if (idx < 2) {
          gsap.from(card, {
            y: 22,
            opacity: 0,
            duration: 0.65,
            delay: idx * 0.08,
            ease: "power3.out",
            clearProps: "transform,opacity"
          });
        } else if (typeof window.ScrollTrigger !== "undefined") {
          gsap.from(card, {
            y: 26,
            opacity: 0,
            duration: 0.62,
            ease: "power2.out",
            clearProps: "transform,opacity",
            scrollTrigger: {
              trigger: card,
              start: "top 88%",
              once: true
            }
          });
        }
      });
    }

    // Subtle pop when user clicks Asset Tab or Weekly/Daily toggle
    document.addEventListener("click", (e) => {
      const hit = e.target && e.target.closest ? e.target.closest(".asset-tab, [data-tf]") : null;
      if (!hit) return;
      const scoreEl = document.getElementById("score");
      if (scoreEl) {
        gsap.fromTo(
          scoreEl,
          { scale: 1.09, opacity: 0.6 },
          { scale: 1, opacity: 1, duration: 0.36, ease: "back.out(1.8)", clearProps: "transform,opacity" }
        );
      }
    });
  }

  /* ---------- 5. Sync kz-theme cookie across .kenvinzone.com ---------- */
  function hookThemeCookie() {
    const btn = document.getElementById("theme-toggle");
    if (!btn) return;
    btn.addEventListener("click", () => {
      setTimeout(() => {
        try {
          const t = document.documentElement.getAttribute("data-theme") || "dark";
          const domainAttr = /\.?kenvinzone\.com$/i.test(location.hostname) ? "; domain=.kenvinzone.com" : "";
          document.cookie = `kz-theme=${t}; path=/${domainAttr}; max-age=31536000; SameSite=Lax`;
        } catch (_) {}
      }, 20);
    });
  }

  function boot() {
    initScrollBeam();
    initSpotlights();
    initGaugeCanvas();
    initScrollCraft();
    hookThemeCookie();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
