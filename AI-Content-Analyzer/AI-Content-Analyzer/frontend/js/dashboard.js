/* ==========================================================================
   dashboard.js - the home page.
   Stat cards count real results from this session. When nothing has run yet
   they show zero rather than a placeholder figure.
   ========================================================================== */

const Dashboard = (() => {

  function stat(key, value, sub) {
    return `
      <div class="stat">
        <div class="k">${UI.esc(key)}</div>
        <div class="v">${UI.esc(value)}</div>
        <div class="sub">${UI.esc(sub)}</div>
      </div>`;
  }

  function refresh() {
    const jobs = App.state.jobs;
    const documents = jobs.filter((job) => job.kind !== "text").length;
    const analyses = jobs.filter((job) => job.result.analysis).length;
    const rewrites = jobs.filter((job) => job.action === "rewrite").length;
    const changes = jobs.reduce((total, job) => {
      const summary = job.result.changes && job.result.changes.summary;
      return total + (summary ? summary.total_changes || 0 : 0);
    }, 0);

    UI.$("#statGrid").innerHTML = [
      stat("Documents", documents, documents ? "processed this session" : "none yet"),
      stat("Analyzed", analyses, analyses ? "analysis runs" : "none yet"),
      stat("Rewritten", rewrites, rewrites ? "natural rewrites" : "none yet"),
      stat("Changes", changes, changes ? "reported by the engine" : "none yet"),
    ].join("");
  }

  function init() {
    refresh();

    const textarea = UI.$("#quickText");
    const analyzeButton = UI.$("#quickAnalyze");
    const rewriteButton = UI.$("#quickRewrite");

    analyzeButton.addEventListener("click", () => {
      const text = textarea.value.trim();
      if (!text) {
        UI.toast("Nothing to analyze", "Paste some text or drop a file first.", "info");
        textarea.focus();
        return;
      }
      App.go("analyzer");
      UI.$("#analyzerInput").value = text;
      UI.$("#analyzerInput").dispatchEvent(new Event("input"));
      UI.$("#analyzerRun").click();
    });

    rewriteButton.addEventListener("click", () => {
      const text = textarea.value.trim();
      if (!text) {
        UI.toast("Nothing to rewrite", "Paste some text or drop a file first.", "info");
        textarea.focus();
        return;
      }
      App.go("rewrite");
      UI.$("#rewriteInput").value = text;
      UI.$("#rewriteRun").click();
    });
  }

  return { init, refresh };
})();

window.Dashboard = Dashboard;
