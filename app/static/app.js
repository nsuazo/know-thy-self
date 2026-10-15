// Know Thy Self — journal page behaviour (autosave, mood/energy, tags, todos, export).
(function () {
  "use strict";

  const statusEl = document.getElementById("save-status");
  const dayEl = document.querySelector("[data-day]");
  const day = dayEl ? dayEl.dataset.day : null;
  let inflight = 0;

  function setStatus(text, cls) {
    if (!statusEl) return;
    statusEl.textContent = text;
    statusEl.className = "save-status" + (cls ? " " + cls : "");
  }

  function timeNow() {
    return new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  }

  async function send(method, url, body, opts) {
    inflight++;
    setStatus("Saving…");
    try {
      const res = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
        keepalive: !!(opts && opts.keepalive),
      });
      if (!res.ok) throw new Error(res.status + " " + res.statusText);
      inflight--;
      if (inflight === 0) setStatus("Saved " + timeNow(), "ok");
      return res;
    } catch (err) {
      inflight--;
      setStatus("Save failed: " + err.message, "err");
      throw err;
    }
  }

  // ---------- textareas: autosave + autogrow ----------
  const pending = new Map(); // key -> {timer}: edits not yet sent
  const chains = new Map();  // key -> promise of the last save for that section
  const queued = new Set();  // keys with a save waiting behind an in-flight one

  function autogrow(ta) {
    ta.style.height = "auto";
    ta.style.height = ta.scrollHeight + 2 + "px";
  }

  function flush(ta, opts) {
    const key = ta.dataset.section;
    const p = pending.get(key);
    if (!p) return;
    clearTimeout(p.timer);
    pending.delete(key);
    const put = () =>
      send("PUT", `/api/day/${day}/section/${key}`, { content: ta.value }, opts).catch(() => {
        // Re-queue so the next edit or blur retries.
        pending.set(key, { timer: null });
      });
    if (opts && opts.keepalive) {
      put(); // page is unloading: queued work would never run, so send now
      return;
    }
    // Saves for one section go out strictly one after another, so an older save can never land
    // after a newer one. The queued save reads ta.value when it runs, so it always sends the latest text.
    if (queued.has(key)) return;
    queued.add(key);
    const prev = chains.get(key) || Promise.resolve();
    chains.set(key, prev.then(() => {
      queued.delete(key);
      return put();
    }));
  }

  document.querySelectorAll("textarea[data-section]").forEach((ta) => {
    autogrow(ta);
    ta.addEventListener("input", () => {
      autogrow(ta);
      const key = ta.dataset.section;
      const p = pending.get(key);
      if (p && p.timer) clearTimeout(p.timer);
      pending.set(key, { timer: setTimeout(() => flush(ta), 800) });
      setStatus("Editing…");
    });
    ta.addEventListener("blur", () => flush(ta));
  });

  window.addEventListener("beforeunload", (e) => {
    if (pending.size === 0 && inflight === 0) return;
    document.querySelectorAll("textarea[data-section]").forEach((ta) => flush(ta, { keepalive: true }));
    e.preventDefault();
  });

  // ---------- mood / energy ----------
  const scales = document.querySelectorAll(".scale[data-meta]");
  function metaPayload() {
    const out = {};
    scales.forEach((s) => {
      out[s.dataset.meta] = s.dataset.value ? Number(s.dataset.value) : null;
    });
    return out;
  }
  scales.forEach((scale) => {
    scale.addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-n]");
      if (!btn) return;
      const n = btn.dataset.n;
      scale.dataset.value = scale.dataset.value === n ? "" : n; // click again to clear
      scale.querySelectorAll("button").forEach((b) =>
        b.classList.toggle("on", b.dataset.n === scale.dataset.value)
      );
      send("PUT", `/api/day/${day}/meta`, metaPayload()).catch(() => {});
    });
  });

  // ---------- tags ----------
  const tagsInput = document.getElementById("tags");
  if (tagsInput) {
    let last = tagsInput.value;
    const saveTags = async () => {
      if (tagsInput.value === last) return;
      last = tagsInput.value;
      try {
        const res = await send("PUT", `/api/day/${day}/tags`, { tags: tagsInput.value });
        const data = await res.json();
        tagsInput.value = last = data.tags.join(", ");
      } catch (_) {}
    };
    tagsInput.addEventListener("change", saveTags);
    tagsInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); saveTags(); }
    });
  }

  // ---------- todos ----------
  const todos = document.getElementById("todos");
  async function todoAction(url, body) {
    try {
      const res = await send("POST", url, body);
      todos.innerHTML = await res.text();
    } catch (_) {}
  }
  if (todos) {
    todos.addEventListener("change", (e) => {
      const id = e.target.dataset.todoToggle;
      if (id) todoAction(`/api/day/${day}/todos/${id}/toggle`);
    });
    todos.addEventListener("click", (e) => {
      const ds = e.target.dataset;
      if (ds.todoDrop) todoAction(`/api/day/${day}/todos/${ds.todoDrop}/drop`);
      else if (ds.todoUndrop) todoAction(`/api/day/${day}/todos/${ds.todoUndrop}/undrop`);
      else if (ds.todoEdit) startEdit(e.target.closest("li"), ds.todoEdit);
    });

    // Inline edit: Enter saves, Escape or clicking away cancels.
    function startEdit(li, id) {
      const span = li.querySelector(".todo-text");
      if (!span) return;
      const input = document.createElement("input");
      input.type = "text";
      input.className = "todo-edit";
      input.maxLength = 500;
      input.value = span.textContent;
      const label = li.querySelector("label");
      label.replaceWith(input);
      input.focus();
      input.select();
      let done = false;
      const cancel = () => {
        if (done) return;
        done = true;
        if (input.isConnected) input.replaceWith(label); // nothing is sent
      };
      input.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter") {
          ev.preventDefault();
          const text = input.value.trim();
          if (!text) return;
          done = true;
          todoAction(`/api/day/${day}/todos/${id}/edit`, { text });
        } else if (ev.key === "Escape") {
          cancel();
        }
      });
      input.addEventListener("blur", cancel);
    }
    const form = document.getElementById("todo-add");
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const input = form.elements.text;
      const text = input.value.trim();
      if (!text) return;
      input.value = "";
      await todoAction(`/api/day/${day}/todos`, { text });
      input.focus();
    });
  }

  // ---------- history: manual export ----------
  const exportBtn = document.getElementById("export-btn");
  if (exportBtn) {
    const exportStatus = document.getElementById("export-status");
    exportBtn.addEventListener("click", async () => {
      exportBtn.disabled = true;
      exportStatus.textContent = "Exporting…";
      try {
        const res = await fetch("/api/export", { method: "POST" });
        if (!res.ok) throw new Error(res.status);
        const data = await res.json();
        exportStatus.textContent = `Done: ${data.written} file(s) updated.`;
      } catch (err) {
        exportStatus.textContent = "Export failed: " + err.message;
      } finally {
        exportBtn.disabled = false;
      }
    });
  }
})();
