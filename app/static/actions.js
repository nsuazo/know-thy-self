// Review page: add a distilled action to tomorrow's todo list.
(function () {
  "use strict";
  const card = document.getElementById("actions");
  if (!card) return;
  const reviewId = card.dataset.review;

  card.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-add-action]");
    if (!btn || btn.disabled) return;
    const row = btn.closest(".action-row");
    const input = row.querySelector("input");
    const text = input.value.trim();
    if (!text) { input.focus(); return; }
    btn.disabled = true;
    btn.textContent = "Adding…";
    try {
      const res = await fetch(`/api/review/${reviewId}/todo`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, index: Number(row.dataset.index) }),
      });
      if (!res.ok) throw new Error(res.status);
      row.classList.add("added");
      input.disabled = true;
      btn.textContent = "Added";
    } catch (err) {
      btn.disabled = false;
      btn.textContent = "Retry";
    }
  });

  card.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target.matches(".action-row input")) {
      e.preventDefault();
      e.target.closest(".action-row").querySelector("[data-add-action]").click();
    }
  });
})();
