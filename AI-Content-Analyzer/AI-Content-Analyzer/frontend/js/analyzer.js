/* ==========================================================================
   analyzer.js - the Text Analyzer page and the shared analysis renderer
   used by the dashboard, the documents page and the rewrite page.

   Every number displayed here comes from the Python response. Nothing is
   estimated, rounded up for effect, or invented when a field is missing.
   ========================================================================== */

const Analyzer = (() => {

  /* ---------------------------- Gauge ---------------------------- */
  function gauge(analysis) {
    const mapping = UI.indication(analysis.ai_likelihood);
    const segments = Array.from({ length: 10 }, (_, index) =>
      `<i class="${index < mapping.level ? "on" : ""}"></i>`
    ).join("");

    return `
      <div class="gauge">
        <div class="label">AI-like linguistic indicators</div>
        <div class="value">${UI.esc(analysis.ai_likelihood || "Inconclusive")}</div>
        <div class="gauge-bar" role="img"
             aria-label="Indicator strength: ${UI.esc(analysis.ai_likelihood || "Inconclusive")}">
          ${segments}
        </div>
        <div class="gauge-foot">
          <span>Confidence: <strong>${UI.esc(analysis.confidence || "Low")}</strong></span>
          <span>Readability: <strong>${UI.esc(analysis.readability || "—")}</strong></span>
          <span>Chunks: <strong>${UI.esc(analysis.chunks_processed)}/${UI.esc(analysis.chunks_total)}</strong></span>
        </div>
        <p class="disclaimer-line">
          These are linguistic indicators, not proof of authorship. No detection
          method — including this one — can reliably tell whether a person or a
          model wrote a text.
        </p>
      </div>`;
  }

  /* ---------------------------- Metric blocks ---------------------------- */
  function metric(name, value, fillPercent, note) {
    const width = Math.max(0, Math.min(100, Number(fillPercent) || 0));
    return `
      <div class="metric">
        <span class="m-name">${UI.esc(name)}</span>
        <span class="m-track"><span class="m-fill" style="width:${width}%"></span></span>
        <span class="m-val" title="${UI.esc(note || "")}">${UI.esc(value)}</span>
      </div>`;
  }

  function writingPattern(stats) {
    if (!stats || !stats.word_count) return "";
    const variation = Number(stats.sentence_length_variation_ratio || 0);
    const diversity = Number(stats.vocabulary_diversity_ratio || 0);
    const repeats = (stats.repeated_phrases || []).length;

    return `
      <div class="block">
        <h4>Writing pattern</h4>
        <div class="metrics">
          ${metric("Sentence variation", variation.toFixed(3), Math.min(variation / 0.8, 1) * 100,
                   "Standard deviation of sentence length divided by the mean")}
          ${metric("Vocabulary diversity", diversity.toFixed(3), diversity * 100,
                   "Unique words divided by total words")}
          ${metric("Avg sentence length", `${stats.average_sentence_length_words} words`,
                   Math.min(stats.average_sentence_length_words / 40, 1) * 100)}
          ${metric("Repeated 3-word phrases", repeats, Math.min(repeats / 10, 1) * 100)}
        </div>
        <div class="meta-row" style="margin-top:14px">
          <span class="badge">${UI.esc(stats.word_count)} words</span>
          <span class="badge">${UI.esc(stats.sentence_count)} sentences</span>
          <span class="badge">${UI.esc(stats.paragraph_count)} paragraphs</span>
          <span class="badge">${UI.esc(stats.unique_word_count)} unique words</span>
        </div>
      </div>`;
  }

  function readability(stats) {
    if (!stats || !stats.word_count) return "";
    const flesch = Number(stats.flesch_reading_ease || 0);
    return `
      <div class="block">
        <h4>Readability</h4>
        <div class="metrics">
          ${metric("Reading ease", `${flesch} (${stats.readability_label || "—"})`,
                   Math.max(0, Math.min(flesch, 100)),
                   "Flesch reading ease: higher is easier")}
          ${metric("Sentence complexity", `${stats.average_sentence_length_words} w/sentence`,
                   Math.min(stats.average_sentence_length_words / 40, 1) * 100)}
          ${metric("Length consistency", stats.sentence_length_standard_deviation,
                   Math.min(stats.sentence_length_standard_deviation / 20, 1) * 100,
                   "Standard deviation of sentence length in words")}
        </div>
      </div>`;
  }

  function indicators(list) {
    if (!list || !list.length) {
      return `<div class="block"><h4>Detected indicators</h4>
              <p class="muted" style="font-size:13.5px">No notable patterns were flagged.</p></div>`;
    }
    const cards = list
      .map(
        (item) => `
        <div class="indicator sev-${UI.esc(item.severity)}">
          <div class="i-head">
            <strong>${UI.esc(item.type)}</strong>
            <span class="badge ${UI.severityClass(item.severity)}">${UI.esc(item.severity)}</span>
          </div>
          <p>${UI.esc(item.explanation)}</p>
        </div>`
      )
      .join("");
    return `<div class="block"><h4>Detected indicators (${list.length})</h4>${cards}</div>`;
  }

  function passageCard(item) {
    return `
      <div class="passage">
        <div class="meta-row">
          <span class="badge">${UI.esc(item.indicator_type || "Unspecified")}</span>
          <span class="badge ${UI.severityClass(item.strength)}">Strength: ${UI.esc(item.strength)}</span>
        </div>
        <blockquote>${UI.esc(item.original)}</blockquote>
        <p class="why"><b>Reason:</b> ${UI.esc(item.reason)}</p>
      </div>`;
  }

  function passages(list) {
    if (!list || !list.length) {
      return `<div class="block"><h4>Flagged passages</h4>
              <p class="muted" style="font-size:13.5px">No individual passages were flagged.</p></div>`;
    }
    const shown = list.slice(0, 3).map(passageCard).join("");
    const more =
      list.length > 3
        ? `<div class="pane-actions">
             <button class="btn btn-ghost btn-sm" data-all-passages type="button">
               View all ${list.length} passages
             </button>
           </div>`
        : "";
    return `<div class="block"><h4>Flagged passages (${list.length})</h4>${shown}${more}</div>`;
  }

  /* ---------------------------- Public renderer ---------------------------- */
  /** Renders a full analysis into `host`. Used by several pages. */
  function render(host, result) {
    if (!host) return;
    const analysis = result.analysis;
    if (!analysis) {
      UI.empty(host, "No analysis available", "This result was produced without an analysis step.");
      return;
    }
    const stats = analysis.statistics || {};
    const warnings = (result.extraction && result.extraction.warnings) || [];

    host.innerHTML = `
      <div class="result-stack">
        ${gauge(analysis)}
        ${analysis.mode === "mock"
          ? `<div class="badge badge-mod" style="align-self:flex-start">
               Offline test mode — local heuristics, not a language model
             </div>`
          : ""}
        <div class="block">
          <h4>Overall assessment</h4>
          <p class="assessment">${UI.esc(analysis.overall_assessment)}</p>
        </div>
        ${writingPattern(stats)}
        ${readability(stats)}
        ${indicators(analysis.indicators)}
        ${passages(analysis.flagged_passages)}
        ${warnings.length
          ? `<div class="block"><h4>Notes</h4>${warnings
              .map((w) => `<p class="muted" style="font-size:13.5px">• ${UI.esc(w)}</p>`)
              .join("")}</div>`
          : ""}
      </div>`;

    const moreButton = host.querySelector("[data-all-passages]");
    if (moreButton) {
      moreButton.addEventListener("click", () => {
        UI.openModal(
          `Flagged passages (${analysis.flagged_passages.length})`,
          analysis.flagged_passages.map(passageCard).join("")
        );
      });
    }
  }

  /* ---------------------------- Page wiring ---------------------------- */
  function init() {
    const input = UI.$("#analyzerInput");
    const counter = UI.$("#analyzerCount");
    const result = UI.$("#analyzerResult");
    const runButton = UI.$("#analyzerRun");

    UI.empty(result, "No analysis yet.", "Paste text on the left and select Analyze Content.");

    input.addEventListener("input", () => {
      counter.textContent = `${UI.wordCount(input.value)} words`;
    });

    runButton.addEventListener("click", () => run(input.value, runButton, result));

    UI.$("#analyzerRewrite").addEventListener("click", () => {
      const text = input.value.trim();
      if (!text) {
        UI.toast("Nothing to rewrite", "Paste some text first.", "info");
        return;
      }
      App.go("rewrite");
      UI.$("#rewriteInput").value = text;
      UI.$("#rewriteRun").click();
    });

    UI.$("#analyzerClear").addEventListener("click", () => {
      input.value = "";
      counter.textContent = "0 words";
      UI.empty(result, "No analysis yet.", "Paste text on the left and select Analyze Content.");
    });

    // Ctrl/Cmd + Enter runs the analysis.
    input.addEventListener("keydown", (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key === "Enter") runButton.click();
    });
  }

  async function run(text, button, host) {
    if (!text || !text.trim()) {
      UI.toast("Nothing to analyze", "Paste some text first.", "info");
      return;
    }
    UI.busy(button, true, "Analyzing…");
    UI.steps(host, ["Preparing content", "Analyzing writing patterns", "Building report"], 1,
             "Analyzing your content");

    const response = await Api.analyzeText(text);
    UI.busy(button, false);

    if (!response.ok) {
      UI.errorPanel(host, response.error, "Try again");
      const retry = host.querySelector("[data-retry]");
      if (retry) retry.addEventListener("click", () => run(text, button, host));
      UI.toast("Analysis failed", Api.friendly(response.error), "error");
      return;
    }

    App.addJob(response, { kind: "text", label: "Pasted text", action: "analysis" });
    render(host, response);
    host.insertAdjacentHTML("beforeend", Downloads.card(response));
    UI.toast("Analysis complete", "Your content has been analyzed.", "ok");
  }

  return { init, render, run, gauge };
})();

window.Analyzer = Analyzer;
