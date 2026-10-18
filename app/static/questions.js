// Questions: answer widgets, skip/restore, settings, the nav count and the quiet background refill.
(function () {
  "use strict";

  async function api(method, url, body) {
    const res = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Error ${res.status}`);
    return data;
  }

  // ---------- nav count ----------
  const badge = document.getElementById("q-badge");
  async function refreshCount() {
    if (!badge) return;
    try {
      const { count } = await api("GET", "/api/questions/waiting");
      badge.textContent = count;
      badge.hidden = !count;
    } catch (_) {}
  }
  refreshCount();

  // ---------- quiet refill (journal page and Questions page) ----------
  const onQuestions = !!document.querySelector(".questions-page");
  const onJournal = !!document.querySelector(".day[data-day]");
  if (onQuestions || onJournal) {
    api("POST", "/api/questions/refill")
      .then((r) => {
        // On the Questions page, reload so the progress of the new batch is shown.
        if (r.started && onQuestions && !document.querySelector(".q-text.dirty")) window.location.reload();
      })
      .catch(() => {});
  }

  // ---------- answer widgets ----------
  function autogrow(ta) {
    ta.style.height = "auto";
    ta.style.height = ta.scrollHeight + 2 + "px";
  }

  function valueOf(w) {
    const kind = w.dataset.kind;
    if (kind === "scale") {
      const on = w.querySelector(".q-scale button.on");
      return on ? Number(on.dataset.v) : null;
    }
    if (kind === "choice" || kind === "claim_check") {
      const on = w.querySelector(".q-pill.on");
      return on ? on.dataset.v : null;
    }
    if (kind === "rank") {
      return w.dataset.ranked === "1" ? [...w.querySelectorAll(".q-rank li")].map((li) => li.dataset.v) : null;
    }
    return null;
  }

  document.querySelectorAll(".q-widget").forEach((w) => {
    const ta = w.querySelector(".q-text");
    const status = w.querySelector(".q-status");
    if (w.dataset.kind === "rank" && w.dataset.answerId) w.dataset.ranked = "1";
    autogrow(ta);
    ta.addEventListener("input", () => { autogrow(ta); ta.classList.add("dirty"); });

    w.addEventListener("click", async (e) => {
      const pick = e.target.closest(".q-scale button, .q-pill");
      if (pick) {
        const group = pick.parentElement;
        const wasOn = pick.classList.contains("on");
        group.querySelectorAll(".on").forEach((b) => b.classList.remove("on"));
        if (!wasOn) pick.classList.add("on"); // click again to clear
        ta.classList.add("dirty");
        return;
      }
      const move = e.target.closest("[data-move]");
      if (move) {
        const li = move.closest("li");
        const sib = Number(move.dataset.move) < 0 ? li.previousElementSibling : li.nextElementSibling;
        if (sib) {
          if (Number(move.dataset.move) < 0) sib.before(li); else sib.after(li);
        }
        w.dataset.ranked = "1";
        ta.classList.add("dirty");
        return;
      }
      if (e.target.closest(".q-cancel")) {
        const art = w.closest(".q-answer");
        art.querySelector(".q-answer-edit").hidden = true;
        art.querySelector(".q-answer-view").hidden = false;
        ta.classList.remove("dirty");
        return;
      }
      if (!e.target.closest(".q-save")) return;

      const text = ta.value.trim();
      const value = valueOf(w);
      if (!text && value === null) {
        status.textContent = "Write an answer or pick an option first.";
        ta.focus();
        return;
      }
      const btn = e.target.closest(".q-save");
      btn.disabled = true;
      status.textContent = "Saving…";
      try {
        const data = w.dataset.answerId
          ? await api("PUT", `/api/answers/${w.dataset.answerId}`, { text, value })
          : await api("POST", `/api/questions/${w.dataset.qid}/answer`, { text, value });
        ta.classList.remove("dirty");
        if (w.dataset.mode === "inline") {
          const card = w.closest(".q-day");
          card.innerHTML =
            '<p class="flash">Saved. <a href="' + data.next + '">See your answer</a> or ' +
            '<a href="/questions">answer another</a>.</p>';
          refreshCount();
        } else {
          window.location.assign(data.next);
        }
      } catch (err) {
        btn.disabled = false;
        status.textContent = "Not saved: " + err.message;
      }
    });
  });

  // Don't lose a half-written answer by navigating away.
  window.addEventListener("beforeunload", (e) => {
    if (document.querySelector(".q-text.dirty")) e.preventDefault();
  });

  // ---------- edit an earlier answer ----------
  document.querySelectorAll("[data-edit-answer]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const art = btn.closest(".q-answer");
      art.querySelector(".q-answer-view").hidden = true;
      const edit = art.querySelector(".q-answer-edit");
      edit.hidden = false;
      const ta = edit.querySelector(".q-text");
      autogrow(ta);
      ta.focus();
    });
  });

  // ---------- later / never / bad ----------
  document.querySelectorAll(".q-skip").forEach((box) => {
    const qid = box.dataset.qid;
    const form = box.querySelector(".q-bad-form");
    box.addEventListener("click", async (e) => {
      const b = e.target.closest("[data-skip]");
      if (!b) return;
      const kind = b.dataset.skip;
      if (kind === "bad") {
        form.hidden = false;
        form.querySelector("input").focus();
        return;
      }
      const ta = document.querySelector(".q-text.dirty");
      if (ta) ta.classList.remove("dirty");
      try {
        if (kind === "bad-confirm") {
          await api("POST", `/api/questions/${qid}/bad`, { reason: form.querySelector("input").value });
        } else {
          await api("POST", `/api/questions/${qid}/${kind}`);
        }
        const card = box.closest(".q-day");
        if (card) {
          card.innerHTML = '<p class="muted small">Skipped. It comes back in 30 days. <a href="/questions">Answer a different one</a>.</p>';
          refreshCount();
        } else {
          window.location.assign("/questions");
        }
      } catch (err) {
        alertBox(box, err.message);
      }
    });
  });

  function alertBox(el, msg) {
    let p = el.querySelector(".q-err");
    if (!p) { p = document.createElement("span"); p.className = "q-err muted small"; el.append(p); }
    p.textContent = msg;
  }

  document.querySelectorAll("[data-restore]").forEach((b) => {
    b.addEventListener("click", async () => {
      try {
        await api("POST", `/api/questions/${b.dataset.restore}/restore`);
        window.location.assign(`/questions?q=${b.dataset.restore}`);
      } catch (err) {
        b.textContent = err.message;
      }
    });
  });

  // ---------- settings ----------
  const saveSettings = document.getElementById("q-settings-save");
  if (saveSettings) {
    saveSettings.addEventListener("click", async () => {
      const st = document.getElementById("q-settings-status");
      const muted = [...document.querySelectorAll("#q-muted input:checked")].map((i) => i.value);
      try {
        await api("PUT", "/api/questions/settings", { focus: document.getElementById("q-focus").value, muted });
        st.textContent = "Saved.";
      } catch (err) {
        st.textContent = "Not saved: " + err.message;
      }
    });
  }
})();
