// Progressive enhancement: the original selects remain the form/state contract.
// One shared listbox, no polling, animation loop, or additional dependency.
(() => {
  const entries = new Map();
  const menu = document.createElement("div");
  menu.id = "pane-select-menu";
  menu.className = "pane-select-menu";
  menu.setAttribute("role", "listbox");
  menu.hidden = true;
  document.body.append(menu);
  let current = null,
    active = -1,
    activeValue = null,
    query = "",
    queryTimer;

  function close(restore = false) {
    if (!current) return;
    const previous = current;
    current = null;
    menu.hidden = true;
    previous.button.setAttribute("aria-expanded", "false");
    previous.button.removeAttribute("aria-activedescendant");
    previous.wrap.classList.remove("is-open");
    clearTimeout(queryTimer);
    query = "";
    if (restore) previous.button.focus({ preventScroll: true });
  }
  function enabled(entry) {
    return [...entry.source.options]
      .map((option, i) => (option.disabled ? -1 : i))
      .filter((i) => i >= 0);
  }
  function highlight(index) {
    active = index;
    activeValue = current?.source.options[index]?.value ?? null;
    [...menu.children].forEach((item, i) =>
      item.classList.toggle("is-active", i === active),
    );
    const item = menu.children[active];
    if (!item || !current) return;
    current.button.setAttribute("aria-activedescendant", item.id);
    item.scrollIntoView({ block: "nearest" });
  }
  function position() {
    if (!current) return;
    const rect = current.button.getBoundingClientRect();
    const bounds = current.button
      .closest(".drawer,.onboarding")
      ?.getBoundingClientRect();
    const scale =
      parseFloat(getComputedStyle(document.documentElement).zoom) || 1;
    const top = Math.max(8, (bounds?.top || 0) + 8);
    const bottom = Math.min(
      innerHeight - 8,
      (bounds?.bottom || innerHeight) - 8,
    );
    const below = bottom - rect.bottom - 6,
      above = rect.top - top - 6;
    const upward =
      below < Math.min(200 * scale, menu.scrollHeight * scale) && above > below;
    const height = Math.max(
      40 * scale,
      Math.min(230 * scale, upward ? above : below),
    );
    menu.style.width = `${rect.width / scale}px`;
    menu.style.maxHeight = `${height / scale}px`;
    menu.style.left = `${rect.left / scale}px`;
    const actualHeight = Math.min(menu.scrollHeight * scale, height);
    menu.style.top = `${(upward ? rect.top - actualHeight - 6 : rect.bottom + 6) / scale}px`;
    menu.dataset.direction = upward ? "up" : "down";
  }
  function renderMenu() {
    if (!current) return;
    const { source, button } = current;
    menu.setAttribute("aria-label", current.name);
    menu.replaceChildren(
      ...[...source.options].map((option, index) => {
        const item = document.createElement("div");
        item.id = `${source.id}-option-${index}`;
        item.className = "pane-select-option";
        item.setAttribute("role", "option");
        item.setAttribute(
          "aria-selected",
          String(index === source.selectedIndex),
        );
        item.setAttribute("aria-disabled", String(option.disabled));
        const label = document.createElement("span");
        label.textContent = option.textContent;
        item.append(label);
        item.addEventListener("pointermove", () => {
          if (!option.disabled && active !== index) highlight(index);
        });
        item.addEventListener("pointerdown", (e) => e.preventDefault());
        item.addEventListener("click", () => choose(index));
        return item;
      }),
    );
    const previousIndex = [...source.options].findIndex(
      (option) => option.value === activeValue && !option.disabled,
    );
    active = previousIndex >= 0 ? previousIndex : source.selectedIndex;
    menu.hidden = false;
    position();
    highlight(active);
    button.setAttribute("aria-expanded", "true");
  }
  function open(entry) {
    if (entry.button.disabled) return;
    close();
    current = entry;
    document.dispatchEvent(new Event("pane-select-open"));
    active = entry.source.selectedIndex;
    activeValue = entry.source.value;
    entry.wrap.classList.add("is-open");
    entry.button.focus({ preventScroll: true });
    renderMenu();
  }
  function choose(index) {
    if (!current || index < 0 || current.source.options[index]?.disabled)
      return;
    const entry = current;
    const changed = entry.source.selectedIndex !== index;
    entry.source.selectedIndex = index;
    close(true);
    sync(entry);
    if (changed) {
      entry.source.dispatchEvent(new Event("input", { bubbles: true }));
      entry.source.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }
  function sync(entry) {
    const { source, button, value } = entry;
    value.textContent =
      source.selectedOptions[0]?.textContent || "Choose an option";
    button.disabled =
      source.disabled ||
      !enabled(entry).length ||
      (source.options.length === 1 && !source.options[0].value);
    button.dataset.tip = source.title || entry.name;
    if (current === entry) {
      if (button.disabled || !button.checkVisibility()) close();
      else renderMenu();
    }
  }
  document.querySelectorAll("select").forEach((source) => {
    const wrap = document.createElement("div");
    wrap.className = "pane-select";
    const button = document.createElement("button");
    button.type = "button";
    button.id = `${source.id}-control`;
    button.className = "pane-select-trigger";
    button.setAttribute("role", "combobox");
    button.setAttribute("aria-haspopup", "listbox");
    button.setAttribute("aria-expanded", "false");
    button.setAttribute("aria-controls", menu.id);
    const value = document.createElement("span");
    value.className = "pane-select-value";
    value.id = `${source.id}-value`;
    const chevron = document.createElement("span");
    chevron.className = "pane-select-chevron";
    chevron.setAttribute("aria-hidden", "true");
    button.append(value, chevron);
    const labels = [...source.labels];
    const name =
      labels.map((label) => label.textContent.trim()).join(" ") ||
      source.title ||
      "Choose an option";
    if (labels.length) {
      labels.forEach((label, index) => {
        label.id ||= `${source.id}-label-${index}`;
        label.addEventListener("click", (event) => {
          event.preventDefault();
          button.focus();
        });
      });
      button.setAttribute(
        "aria-labelledby",
        `${labels.map((l) => l.id).join(" ")} ${value.id}`,
      );
    } else button.setAttribute("aria-label", name);
    source.before(wrap);
    wrap.append(source, button);
    source.classList.add("pane-select-source");
    source.tabIndex = -1;
    source.setAttribute("aria-hidden", "true");
    const entry = { source, wrap, button, value, name };
    entries.set(source, entry);
    button.addEventListener("click", () =>
      current === entry ? close() : open(entry),
    );
    button.addEventListener("keydown", (event) => {
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      if (event.key === "Tab") {
        close();
        return;
      }
      if (event.key === "Escape") {
        if (current) {
          event.preventDefault();
          event.stopPropagation();
          close(true);
        }
        return;
      }
      if (["Enter", " "].includes(event.key)) {
        event.preventDefault();
        if (current === entry) choose(active);
        else open(entry);
        return;
      }
      if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
        event.preventDefault();
        if (current !== entry) {
          open(entry);
          if (event.key === "ArrowDown" || event.key === "ArrowUp") return;
        }
        const options = enabled(entry),
          index = options.indexOf(active);
        highlight(
          event.key === "Home"
            ? options[0]
            : event.key === "End"
              ? options.at(-1)
              : options[
                  (index +
                    (event.key === "ArrowDown" ? 1 : options.length - 1)) %
                    options.length
                ],
        );
      } else if (event.key.length === 1) {
        event.preventDefault();
        if (current !== entry) open(entry);
        clearTimeout(queryTimer);
        query += event.key.toLocaleLowerCase();
        const match = enabled(entry).find((i) =>
          entry.source.options[i].textContent
            .trim()
            .toLocaleLowerCase()
            .startsWith(query),
        );
        if (match !== undefined) highlight(match);
        queryTimer = setTimeout(() => {
          query = "";
        }, 700);
      }
    });
    button.addEventListener("blur", () => {
      if (current === entry) close();
    });
    source.addEventListener("change", () => sync(entry));
    new MutationObserver(() => sync(entry)).observe(source, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
      attributeFilter: ["disabled", "selected", "label", "value"],
    });
    sync(entry);
  });
  document.addEventListener(
    "pointerdown",
    (event) => {
      if (
        current &&
        !current.wrap.contains(event.target) &&
        !menu.contains(event.target)
      )
        close();
    },
    true,
  );
  document.addEventListener(
    "scroll",
    (event) => {
      if (current && !menu.contains(event.target)) close();
    },
    true,
  );
  window.addEventListener("resize", () => close());
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) close();
  });
  // Navigation/setup changes can hide a trigger while its option list is open.
  new MutationObserver(() => {
    if (current && !current.button.checkVisibility()) close();
  }).observe(document.querySelector(".workspace"), {
    subtree: true,
    attributes: true,
    attributeFilter: ["hidden"],
  });
  window.paneSelects = { sync: () => entries.forEach(sync) };
})();
