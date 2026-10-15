// Know Thy Self — LLM status badge and background-job UI (start, poll, progress, redirect).
(function () {
  "use strict";

  // ---------- status badge ----------
  const badge = document.getElementById("llm-badge");
  async function refreshBadge() {
    if (!badge) return;
    try {
      const res = await fetch("/api/llm/status");
      const data = await res.json();
      badge.className = "llm-badge " + (data.ok ? "on" : "off");
      badge.title = data.ok ? `LLM server online (${data.host})` : `LLM server unreachable (${data.host}): ${data.detail}`;
      badge.querySelector(".llm-label").textContent = data.ok ? "LLM online" : "LLM offline";
    } catch (_) {
      badge.className = "llm-badge off";
      badge.querySelector(".llm-label").textContent = "LLM ?";
    }
  }
  refreshBadge();
  setInterval(refreshBadge, 30000);

  // ---------- background jobs ----------
  const root = document.querySelector(".job-ui");
  if (!root) return;

  const $ = (sel) => root.querySelector(sel);
  const progress = $(".job-progress");
  const text = $(".job-text");
  const clock = $(".job-time");
  const bar = $(".job-bar");
  const barFill = $(".job-bar-fill");
  const hint = $(".job-hint");
  const errorBox = $(".job-error");
  const errorText = $(".job-error-text");
  const retryBtn = $(".job-retry");

  let pollTimer = null;
  let clockTimer = null;
  let startedAt = 0;
  let lastStart = null;

  function setBusy(busy) {
    progress.hidden = !busy;
    hint.hidden = !busy;
    if (!busy) bar.hidden = true;
    document.querySelectorAll("[data-job-lock]").forEach((el) => {
      if (busy) {
        el.dataset.wasDisabled = el.disabled ? "1" : "";
        el.disabled = true;
      } else {
        el.disabled = el.dataset.wasDisabled === "1";
      }
    });
  }

  function tick() {
    const s = Math.floor((Date.now() - startedAt) / 1000);
    clock.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  }

  function stop() {
    clearInterval(pollTimer);
    clearInterval(clockTimer);
  }

  function fail(message) {
    stop();
    setBusy(false);
    errorText.textContent = message;
    errorBox.hidden = !message;
    refreshBadge();
  }

  function watch(jobId) {
    startedAt = Date.now();
    errorBox.hidden = true;
    setBusy(true);
    tick();
    clockTimer = setInterval(tick, 1000);
    pollTimer = setInterval(async () => {
      try {
        const res = await fetch(`/api/jobs/${jobId}`);
        if (!res.ok) throw new Error(res.status);
        const job = await res.json();
        text.textContent = job.progress_label || (job.status === "queued" ? "Queued…" : "Working…");
        if (job.progress_total > 0) {
          bar.hidden = false;
          barFill.style.width = `${Math.round((100 * job.progress_done) / job.progress_total)}%`;
        }
        if (job.status === "done") {
          stop();
          window.location.assign(job.next);
        } else if (job.status === "error") {
          fail(job.error || "The job failed.");
        }
      } catch (_) {
        // Transient poll failure (e.g. the app restarting); keep trying.
      }
    }, 2000);
  }

  async function run(startFn) {
    if (root.dataset.starting === "1") return; // ignore double clicks while the request is out
    root.dataset.starting = "1";
    try {
      await start(startFn);
    } finally {
      root.dataset.starting = "";
    }
  }

  async function start(startFn) {
    lastStart = startFn;
    errorBox.hidden = true;
    let res;
    try {
      res = await startFn();
    } catch (err) {
      fail(err && err.message ? err.message : "Could not reach the journal server.");
      return;
    }
    if (!res) return;
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      fail(typeof data.detail === "string" ? data.detail : `Error ${res.status}`);
      return;
    }
    watch(data.job_id);
  }

  function post(url, body) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
  }

  // Review form
  const form = document.getElementById("review-form");
  if (form) {
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      run(async () => {
        const scope = form.elements.scope.value;
        const perspectives = [...form.querySelectorAll("input[name=perspective]:checked")].map((i) => i.value);
        if (perspectives.length === 0) throw new Error("Pick at least one perspective.");
        const distill = form.elements.distill ? form.elements.distill.checked : true;
        return post("/api/review", { scope, perspectives, distill });
      });
    });
    const setAll = (v) => form.querySelectorAll("input[name=perspective]").forEach((i) => (i.checked = v));
    document.getElementById("persp-all").addEventListener("click", () => setAll(true));
    const resetBtn = document.getElementById("persp-default");
    if (resetBtn) {
      resetBtn.addEventListener("click", () =>
        form.querySelectorAll("input[name=perspective]").forEach((i) => (i.checked = i.defaultChecked))
      );
    }
    document.getElementById("persp-none").addEventListener("click", () => setAll(false));
  }

  // Buttons that start a job at a fixed endpoint (profile, summaries)
  document.querySelectorAll("[data-job-endpoint]").forEach((btn) => {
    btn.addEventListener("click", () => run(() => post(btn.dataset.jobEndpoint)));
  });

  retryBtn.addEventListener("click", () => lastStart && run(lastStart));

  // Resume watching if a job was already running when the page loaded.
  if (root.dataset.activeJob) watch(Number(root.dataset.activeJob));
})();
