// Know Thy Self — LLM status badge and the review page (start job, poll, redirect).
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

  // ---------- review page ----------
  const form = document.getElementById("review-form");
  if (!form) return;

  const runBtn = document.getElementById("run-btn");
  const progress = document.getElementById("review-progress");
  const progressText = document.getElementById("progress-text");
  const progressTime = document.getElementById("progress-time");
  const progressHint = document.getElementById("progress-hint");
  const errorBox = document.getElementById("review-error");
  const errorText = document.getElementById("review-error-text");
  const retryBtn = document.getElementById("review-retry");

  let pollTimer = null;
  let clockTimer = null;
  let startedAt = 0;

  function setBusy(busy) {
    runBtn.disabled = busy;
    progress.hidden = !busy;
    progressHint.hidden = !busy;
    form.querySelectorAll("input").forEach((i) => (i.disabled = busy));
  }

  function tickClock() {
    const s = Math.floor((Date.now() - startedAt) / 1000);
    progressTime.textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  }

  function stopTimers() {
    clearInterval(pollTimer);
    clearInterval(clockTimer);
  }

  function fail(message) {
    stopTimers();
    setBusy(false);
    errorText.textContent = message;
    errorBox.hidden = false;
    refreshBadge();
  }

  function watch(jobId) {
    startedAt = Date.now();
    setBusy(true);
    tickClock();
    clockTimer = setInterval(tickClock, 1000);
    pollTimer = setInterval(async () => {
      try {
        const res = await fetch(`/api/jobs/${jobId}`);
        if (!res.ok) throw new Error(res.status);
        const job = await res.json();
        progressText.textContent = job.status === "queued" ? "Queued…" : "Thinking…";
        if (job.status === "done") {
          stopTimers();
          window.location.href = `/review/${job.result_id}`;
        } else if (job.status === "error") {
          fail(job.error || "The review failed.");
        }
      } catch (_) {
        // Transient poll failure (e.g. app restarting); keep trying.
      }
    }, 2000);
  }

  async function run() {
    errorBox.hidden = true;
    const scope = form.elements.scope.value;
    const perspectives = [...form.querySelectorAll("input[name=perspective]:checked")].map((i) => i.value);
    if (perspectives.length === 0) {
      fail("Pick at least one perspective.");
      return;
    }
    runBtn.disabled = true;
    let res;
    try {
      res = await fetch("/api/review", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scope, perspectives }),
      });
    } catch (_) {
      fail("Could not reach the journal server.");
      return;
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      fail(typeof data.detail === "string" ? data.detail : `Error ${res.status}`);
      return;
    }
    watch(data.job_id);
  }

  form.addEventListener("submit", (e) => { e.preventDefault(); run(); });
  retryBtn.addEventListener("click", run);
  document.getElementById("persp-all").addEventListener("click", () =>
    form.querySelectorAll("input[name=perspective]").forEach((i) => (i.checked = true)));
  document.getElementById("persp-none").addEventListener("click", () =>
    form.querySelectorAll("input[name=perspective]").forEach((i) => (i.checked = false)));

  // Resume watching if a job was already running when the page loaded.
  const active = form.dataset.activeJob;
  if (active) watch(Number(active));
})();
