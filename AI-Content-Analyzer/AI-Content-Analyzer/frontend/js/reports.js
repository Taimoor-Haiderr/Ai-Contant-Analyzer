/* ==========================================================================
   reports.js - the session report library and the history list.
   There is no database: everything here describes results produced in this
   browser session, and both views say so plainly.
   ========================================================================== */

const Reports = (() => {

  const KIND_LABEL = { pdf: "PDF", docx: "DOCX", csv: "CSV", xlsx: "XLSX", text: "TXT" };

  function row(job) {
    const downloads = job.downloads || [];
    const indication = job.result.analysis
      ? UI.indication(job.result.analysis.ai_likelihood)
      : null;

    return `
      <div class="list-row" data-job="${UI.esc(job.id)}">
        <span class="list-icon">${UI.esc(KIND_LABEL[job.kind] || "TXT")}</span>
        <div class="list-main">
          <strong>${UI.esc(job.label)}</strong>
          <div class="sub">
            ${UI.esc(job.action === "rewrite" ? "Natural rewrite" : "Analysis")}
            · ${UI.esc(UI.timeAgo(job.createdAt))}
            ${downloads.length ? ` · ${downloads.length} file(s)` : ""}
          </div>
        </div>
        ${indication ? `<span class="badge ${indication.cls}">${UI.esc(
          job.result.analysis.ai_likelihood
        )}</span>` : ""}
        <div class="list-actions">
          <button class="btn btn-ghost btn-sm" data-view="${UI.esc(job.id)}" type="button">View</button>
          <button class="btn btn-quiet btn-sm" data-export="${UI.esc(job.jobId)}" type="button">Download</button>
        </div>
      </div>`;
  }

  function list(host, jobs, emptyTitle, emptyMessage) {
    if (!host) return;
    if (!jobs.length) {
      UI.empty(host, emptyTitle, emptyMessage);
      return;
    }
    host.innerHTML = `<div class="list">${jobs.map(row).join("")}</div>`;
    host.querySelectorAll("[data-view]").forEach((button) => {
      button.addEventListener("click", () => view(button.dataset.view));
    });
  }

  /** Opens a stored result in the page it belongs to. */
  function view(id) {
    const job = App.state.jobs.find((item) => item.id === id);
    if (!job) {
      UI.toast("Result unavailable", "That result is no longer in this session.", "info");
      return;
    }
    if (job.action === "rewrite") {
      App.go("rewrite");
      Rewriter.render(UI.$("#rewriteResult"), job.result);
    } else {
      App.go("analyzer");
      const host = UI.$("#analyzerResult");
      Analyzer.render(host, job.result);
      host.insertAdjacentHTML("beforeend", Downloads.card(job.result));
    }
  }

  function refresh() {
    const jobs = App.state.jobs;
    const query = (UI.$("#globalSearch").value || "").trim().toLowerCase();
    const filtered = query
      ? jobs.filter((job) => job.label.toLowerCase().includes(query))
      : jobs;

    list(
      UI.$("#reportsList"),
      filtered,
      query ? "No matching results." : "No reports yet.",
      query
        ? "Try a different search term."
        : "Analyze text or upload a document, then use Prepare downloads to generate report files."
    );

    list(
      UI.$("#historyList"),
      filtered,
      query ? "No matching results." : "No analysis yet.",
      query
        ? "Try a different search term."
        : "Upload a document or paste text to get started."
    );

    const recent = UI.$("#recentList");
    list(
      recent,
      jobs.slice(0, 5),
      "No analysis yet.",
      "Upload a document or paste text to get started."
    );
  }

  function init() {
    UI.$("#clearHistory").addEventListener("click", () => App.clearSession());
    UI.$("#globalSearch").addEventListener("input", refresh);
    refresh();
  }

  return { init, refresh, view };
})();

window.Reports = Reports;
