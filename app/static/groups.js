// Remembers which template groups are collapsed on the day page (per browser; optional).
(function () {
  "use strict";
  const KEY = "kts-collapsed-groups";
  const groups = document.querySelectorAll("details.group[data-group]");
  if (!groups.length) return;

  let collapsed = [];
  try { collapsed = JSON.parse(localStorage.getItem(KEY) || "[]"); } catch (_) {}
  groups.forEach((g) => {
    if (collapsed.includes(g.dataset.group)) g.open = false;
    g.addEventListener("toggle", () => {
      const set = new Set(collapsed);
      if (g.open) set.delete(g.dataset.group); else set.add(g.dataset.group);
      collapsed = [...set];
      try { localStorage.setItem(KEY, JSON.stringify(collapsed)); } catch (_) {}
      // Textareas measured while hidden have no height; re-measure when a group opens.
      if (g.open) g.querySelectorAll("textarea").forEach((ta) => {
        ta.style.height = "auto";
        ta.style.height = ta.scrollHeight + 2 + "px";
      });
    });
  });
})();
