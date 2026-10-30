function normalizeText(value) {
  return value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLocaleLowerCase("fr");
}

document.addEventListener("input", (event) => {
  const search = event.target.closest(".common-ingredient-search");
  if (!search) return;

  const query = normalizeText(search.value.trim());
  const picker = search.closest(".common-ingredient-picker");

  picker.querySelectorAll(".common-ingredient-group").forEach((group) => {
    let visibleOptions = 0;
    group.querySelectorAll(".common-ingredient-option").forEach((option) => {
      const matches = normalizeText(option.textContent).includes(query);
      option.hidden = !matches;
      if (matches) visibleOptions += 1;
    });
    group.hidden = visibleOptions === 0;
  });
});

document.addEventListener("click", (event) => {
  const option = event.target.closest(".common-ingredient-option");
  if (!option) return;

  const picker = option.closest(".common-ingredient-picker");
  const form = picker.closest("form");
  const ingredients = form.querySelector('textarea[name="ingredients"]');
  const name = option.dataset.ingredient;
  const entry = option.dataset.entry;
  const currentLines = ingredients.value.trimEnd();
  ingredients.value = `${currentLines}${currentLines ? "\n" : ""}${entry}`;
  picker.querySelector(".common-ingredient-status").textContent =
    `${name} ajouté à la recette.`;
  ingredients.focus();
});

document.addEventListener("submit", (event) => {
  const form = event.target.closest(".delete-recipe-form");
  if (form && !window.confirm(form.dataset.confirm)) {
    event.preventDefault();
  }
});

document.addEventListener("click", async (event) => {
  const button = event.target.closest(".share-shopping-list");
  if (!button) return;

  const panel = button.closest(".shopping-panel");
  const status = panel.querySelector(".shopping-share-status");
  const week = `Week of ${panel.dataset.weekStart}`;
  const lines = ["Shopping list", week, ""];

  panel.querySelectorAll(".shopping-group").forEach((group) => {
    const heading = group.querySelector(".shopping-group-heading")?.textContent.trim();
    if (heading) lines.push(heading);
    group.querySelectorAll(".shopping-list li").forEach((item) => {
      const checked = item.classList.contains("is-checked") ? "x" : " ";
      const name = item.querySelector(".item-name").textContent.trim();
      const quantity = item.querySelector(".item-quantity").textContent.trim();
      lines.push(`- [${checked}] ${quantity} ${name}`);
    });
    if (heading) lines.push("");
  });
  const text = lines.join("\n").trim();

  if (typeof navigator.share === "function") {
    try {
      await navigator.share({ title: "Shopping list", text });
      status.textContent = "Shopping list shared.";
      return;
    } catch (error) {
      if (error && error.name === "AbortError") return;
    }
  }

  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      status.textContent = "Shopping list copied. Paste it into Notes or Keep.";
      return;
    } catch {
      status.textContent =
        "Sharing or copying isn't available here. Download the .txt file instead.";
      return;
    }
  }

  status.textContent =
    "Sharing or copying isn't available here. Download the .txt file instead.";
});
