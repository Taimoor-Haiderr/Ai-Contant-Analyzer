/* ==========================================================================
   downloads.js - turns backend download tokens into real links.
   Nothing here invents a file; every entry comes from the server response.
   ========================================================================== */

const Downloads = (() => {

  const ICON = `<svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/></svg>`;

  /** Renders whatever downloads a result currently carries. */
  function render(result) {
    const items = (result && result.downloads) || [];
    if (!items.length) {
      return `<p class="muted" style="font-size:13.5px">No files generated yet.
              Use <strong>Prepare downloads</strong> to create them.</p>`;
    }
    const links = items
      .map(
        (item) => `
        <a class="download-item" href="${Api.downloadUrl(item.token)}" download>
          ${ICON}
          <span>
            <strong>${UI.esc(item.label)}</strong>
            <small>${UI.esc(item.filename)}</small>
          </span>
        </a>`
      )
      .join("");
    return `<div class="download-grid">${links}</div>`;
  }

  /** Full downloads card, including the button that asks the engine to export. */
  function card(result) {
    return `
      <section class="card" data-downloads-card>
        <div class="card-head">
          <h3>Downloads</h3>
          <p>Original files are never modified. Rewrites are always written to new files.</p>
        </div>
        <div data-download-list>${render(result)}</div>
        <div class="pane-actions">
          <button class="btn btn-ghost btn-sm" data-export="${UI.esc(result.job_id || "")}" type="button">
            Prepare downloads
          </button>
        </div>
      </section>`;
  }

  /**
   * Asks the backend to write the report/export files for a job, then
   * refreshes the link list in place.
   */
  async function prepare(jobId, button, listHost) {
    if (!jobId) {
      UI.toast("Nothing to export", "Run an analysis first.", "info");
      return;
    }
    UI.busy(button, true, "Preparing…");
    const formats = App.state.prefs.formats;
    const response = await Api.exportJob(jobId, formats);
    UI.busy(button, false);

    if (!response.ok) {
      UI.toast("Export failed", Api.friendly(response.error), "error");
      return;
    }

    const job = App.findJob(jobId);
    if (job) job.downloads = response.downloads;
    if (listHost) listHost.innerHTML = render({ downloads: response.downloads });

    App.saveSession();
    Reports.refresh();
    UI.toast("Files ready", `${response.files.length} file(s) generated.`, "ok");
  }

  /** Delegated click handling for every export button on the page. */
  function bind() {
    document.addEventListener("click", (event) => {
      const button = event.target.closest("[data-export]");
      if (!button) return;
      const card = button.closest("[data-downloads-card]");
      prepare(button.dataset.export, button, card && card.querySelector("[data-download-list]"));
    });
  }

  return { render, card, prepare, bind };
})();

window.Downloads = Downloads;
