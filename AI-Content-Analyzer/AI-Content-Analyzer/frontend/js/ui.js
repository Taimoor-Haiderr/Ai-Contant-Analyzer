/* ==========================================================================
   ui.js - shared presentation helpers used by every page module.
   ========================================================================== */

const UI = (() => {

  const $ = (selector, scope = document) => scope.querySelector(selector);
  const $$ = (selector, scope = document) => Array.from(scope.querySelectorAll(selector));

  /** Always escape backend text before inserting it into innerHTML. */
  function esc(value) {
    if (value === null || value === undefined) return "";
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function bytes(size) {
    if (!size && size !== 0) return "";
    const units = ["B", "KB", "MB", "GB"];
    let value = Number(size);
    let unit = 0;
    while (value >= 1024 && unit < units.length - 1) {
      value /= 1024;
      unit += 1;
    }
    return `${value < 10 && unit > 0 ? value.toFixed(1) : Math.round(value)} ${units[unit]}`;
  }

  function timeAgo(iso) {
    if (!iso) return "";
    const then = new Date(iso).getTime();
    if (Number.isNaN(then)) return "";
    const seconds = Math.round((Date.now() - then) / 1000);
    if (seconds < 60) return "just now";
    if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
    return new Date(iso).toLocaleDateString();
  }

  function truncate(text, max = 120) {
    const clean = String(text || "").replace(/\s+/g, " ").trim();
    return clean.length > max ? `${clean.slice(0, max - 1)}…` : clean;
  }

  /** Maps an indication label to a badge class and a 0-10 bar level. */
  function indication(label) {
    const value = String(label || "").toLowerCase();
    if (value.startsWith("high")) return { cls: "badge-high", level: 8 };
    if (value.startsWith("moderate")) return { cls: "badge-mod", level: 5 };
    if (value.startsWith("low")) return { cls: "badge-low", level: 2 };
    return { cls: "badge-none", level: 0 };
  }

  function severityClass(level) {
    const value = String(level || "").toLowerCase();
    if (value === "high") return "badge-high";
    if (value === "moderate") return "badge-mod";
    return "badge-low";
  }

  /* ---------------------------- Toasts ---------------------------- */
  function toast(title, message, kind = "info") {
    const host = $("#toasts");
    if (!host) return;
    const node = document.createElement("div");
    node.className = `toast toast-${kind}`;
    node.innerHTML = `<div><strong>${esc(title)}</strong>${
      message ? `<p>${esc(message)}</p>` : ""
    }</div>`;
    host.appendChild(node);
    setTimeout(() => {
      node.style.transition = "opacity .25s, transform .25s";
      node.style.opacity = "0";
      node.style.transform = "translateX(14px)";
      setTimeout(() => node.remove(), 260);
    }, kind === "error" ? 6500 : 3800);
  }

  /* ---------------------------- Modal ---------------------------- */
  let lastFocused = null;

  function openModal(title, html) {
    const modal = $("#modal");
    lastFocused = document.activeElement;
    $("#modalTitle").textContent = title;
    $("#modalBody").innerHTML = html;
    modal.hidden = false;
    document.body.style.overflow = "hidden";
    const closer = modal.querySelector("[data-close]");
    if (closer) closer.focus();
  }

  function closeModal() {
    const modal = $("#modal");
    if (!modal || modal.hidden) return;
    modal.hidden = true;
    document.body.style.overflow = "";
    if (lastFocused && lastFocused.focus) lastFocused.focus();
  }

  /* ---------------------------- Clipboard ---------------------------- */
  async function copy(text, button) {
    try {
      await navigator.clipboard.writeText(text);
    } catch (err) {
      const helper = document.createElement("textarea");
      helper.value = text;
      helper.setAttribute("readonly", "");
      helper.style.position = "fixed";
      helper.style.opacity = "0";
      document.body.appendChild(helper);
      helper.select();
      try { document.execCommand("copy"); } catch (e) { /* ignore */ }
      helper.remove();
    }
    if (button) {
      const original = button.textContent;
      button.textContent = "Copied ✓";
      button.disabled = true;
      setTimeout(() => {
        button.textContent = original;
        button.disabled = false;
      }, 1500);
    }
  }

  /* ---------------------------- Loading / states ---------------------------- */
  function busy(button, isBusy, busyLabel) {
    if (!button) return;
    if (isBusy) {
      button.dataset.label = button.textContent;
      button.textContent = busyLabel || "Working…";
      button.disabled = true;
    } else {
      if (button.dataset.label) button.textContent = button.dataset.label;
      button.disabled = false;
    }
  }

  function skeleton(host) {
    if (!host) return;
    host.innerHTML = `
      <div class="skeleton">
        <div class="sk-block"></div>
        <div class="sk-line w-80"></div>
        <div class="sk-line w-60"></div>
        <div class="sk-block"></div>
        <div class="sk-line w-40"></div>
      </div>`;
  }

  /**
   * Renders real processing steps. `current` is the index in progress;
   * everything before it is complete. Nothing here fakes a percentage.
   */
  function steps(host, labels, current, title) {
    if (!host) return;
    const rows = labels
      .map((label, index) => {
        const state = index < current ? "is-done" : index === current ? "is-active" : "";
        const mark = index < current ? "✓" : index === current ? "" : "○";
        return `<div class="step ${state}">
                  <span class="step-mark">${mark}</span><span>${esc(label)}</span>
                </div>`;
      })
      .join("");
    host.innerHTML = `
      <div class="card">
        <div class="card-head"><h3>${esc(title || "Processing")}</h3></div>
        <div class="steps">${rows}</div>
        <div class="progress-line"><i></i></div>
      </div>`;
  }

  function empty(host, title, message) {
    if (!host) return;
    host.innerHTML = `
      <div class="empty">
        <svg viewBox="0 0 24 24" aria-hidden="true" stroke-linecap="round" stroke-linejoin="round">
          <path d="M13 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V9z"/><path d="M13 3v6h6"/>
        </svg>
        <h4>${esc(title)}</h4>
        <p>${esc(message)}</p>
      </div>`;
  }

  function errorPanel(host, error, retryLabel) {
    if (!host) return;
    const message = Api.friendly(error);
    host.innerHTML = `
      <div class="card error-panel">
        <div class="ring">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 8v5M12 17h.01"/><circle cx="12" cy="12" r="9"/></svg>
        </div>
        <h4>Something went wrong.</h4>
        <p>${esc(message)}</p>
        ${retryLabel ? `<div class="pane-actions"><button class="btn btn-ghost" data-retry type="button">${esc(retryLabel)}</button></div>` : ""}
      </div>`;
  }

  function successPanel(message, actionsHtml) {
    return `
      <div class="success-panel">
        <span class="tick"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 13 4 4L19 7"/></svg></span>
        <div style="flex:1">
          <strong>${esc(message)}</strong>
        </div>
        <div class="pane-actions">${actionsHtml || ""}</div>
      </div>`;
  }

  function wordCount(text) {
    const trimmed = String(text || "").trim();
    return trimmed ? trimmed.split(/\s+/).length : 0;
  }

  return {
    $, $$, esc, bytes, timeAgo, truncate, indication, severityClass,
    toast, openModal, closeModal, copy, busy, skeleton, steps, empty,
    errorPanel, successPanel, wordCount,
  };
})();

window.UI = UI;
