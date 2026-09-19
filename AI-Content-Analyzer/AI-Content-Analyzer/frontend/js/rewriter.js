/* ==========================================================================
   rewriter.js - the Natural Rewrite workspace, the before/after view and
   the change report. Every count and every change entry comes straight from
   the Python response; nothing is generated in the browser.
   ========================================================================== */

const Rewriter = (() => {

  /* ---------------------------- Before / after ---------------------------- */
  function beforeAfter(result) {
    const original = (result.rewrite && result.rewrite.original) || "";
    const rewritten = (result.rewrite && result.rewrite.rewritten) || "";

    return `
      <section class="card">
        <div class="card-head">
          <h3>Before &amp; after</h3>
          <p>Improve clarity and natural flow while preserving meaning.</p>
        </div>
        <div class="ba-grid">
          <div class="ba-col">
            <div class="ba-head">
              <h4>Original</h4>
              <button class="btn btn-quiet btn-sm" data-copy="original" type="button">Copy original</button>
            </div>
            <div class="ba-text" data-original>${UI.esc(original)}</div>
          </div>
          <div class="ba-col after">
            <div class="ba-head">
              <h4>Natural rewrite</h4>
              <button class="btn btn-quiet btn-sm" data-copy="rewritten" type="button">Copy rewrite</button>
            </div>
            <div class="ba-text" data-rewritten>${UI.esc(rewritten)}</div>
          </div>
        </div>
      </section>`;
  }

  /* ---------------------------- Change summary ---------------------------- */
  function summary(changes) {
    const info = changes.summary || {};
    const byType = info.changes_by_type || {};
    const entries = Object.entries(byType).sort((a, b) => b[1] - a[1]);
    const max = entries.length ? Math.max(...entries.map((e) => e[1])) : 1;

    const bars = entries.length
      ? entries
          .map(
            ([name, count]) => `
          <div class="type-bar">
            <span class="t-name" title="${UI.esc(name)}">${UI.esc(name)}</span>
            <span class="t-track"><span class="t-fill" style="width:${(count / max) * 100}%"></span></span>
            <span class="t-num">${UI.esc(count)}</span>
          </div>`
          )
          .join("")
      : `<p class="muted" style="font-size:13.5px">No change categories were reported.</p>`;

    return `
      <section class="card">
        <div class="card-head">
          <h3>Changes made</h3>
          <p>Counts reported by the engine for this rewrite.</p>
        </div>
        <div class="change-summary">
          <div class="change-total">
            <div class="n">${UI.esc(info.total_changes || 0)}</div>
            <div class="l">Total changes</div>
            <div class="split-n">${UI.esc(info.major_changes || 0)} major ·
                                  ${UI.esc(info.minor_changes || 0)} minor</div>
          </div>
          <div class="type-bars">${bars}</div>
        </div>
        <div class="meta-row" style="margin-top:20px">
          <span class="badge">Words: ${UI.esc(info.original_word_count || 0)} →
                              ${UI.esc(info.rewritten_word_count || 0)}</span>
        </div>
        <p class="muted" style="font-size:13.5px;margin-top:12px">
          <strong>Meaning:</strong> ${UI.esc(info.meaning_preservation_status || "Not reported")}<br>
          <strong>Facts:</strong> ${UI.esc(info.facts_preserved_status || "Not reported")}
        </p>
        ${(info.verification_notes || []).length
          ? `<p class="muted" style="font-size:13px;margin-top:10px">${info.verification_notes
              .map((note) => `• ${UI.esc(note)}`)
              .join("<br>")}</p>`
          : ""}
      </section>`;
  }

  /* ---------------------------- Change report ---------------------------- */
  function changeCards(list) {
    return list
      .map((change, index) => {
        const number = String(index + 1).padStart(2, "0");
        return `
        <article class="change">
          <button class="change-head" type="button" aria-expanded="false">
            <span class="change-no">CHANGE #${number}</span>
            <span class="ch-title">${UI.esc(UI.truncate(change.original || change.rewritten, 70))}</span>
            <span class="badge">${UI.esc(change.change_type)}</span>
            <svg class="chev" viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>
          </button>
          <div class="change-body">
            <div class="change-pair">
              <div class="from"><span class="tag">Original</span>${UI.esc(change.original) || "<em>—</em>"}</div>
              <div class="to"><span class="tag">Rewritten</span>${UI.esc(change.rewritten) || "<em>—</em>"}</div>
            </div>
            <p class="change-reason"><strong>Reason:</strong> ${UI.esc(change.reason || "Not supplied.")}</p>
          </div>
        </article>`;
      })
      .join("");
  }

  function changeReport(changes) {
    const list = changes.changes || [];
    if (!list.length) {
      return `
        <section class="card">
          <div class="card-head"><h3>What changed?</h3></div>
          <div class="empty">
            <h4>No individual changes were reported.</h4>
            <p>The engine did not record any edits for this content.</p>
          </div>
        </section>`;
    }

    return `
      <section class="card" data-change-report>
        <div class="card-head">
          <h3>What changed?</h3>
          <p>Every transformation the engine reported, with its reason.</p>
        </div>
        <div class="change-toolbar">
          <span class="badge">${list.length} change${list.length === 1 ? "" : "s"}</span>
          <div class="pane-actions" style="margin:0">
            <button class="btn btn-quiet btn-sm" data-expand-all type="button">Expand all</button>
            <button class="btn btn-quiet btn-sm" data-collapse-all type="button">Collapse all</button>
          </div>
        </div>
        ${changeCards(list)}
      </section>`;
  }

  /* ---------------------------- Tabular results ---------------------------- */
  /** CSV / XLSX rewrites report changed cells rather than a text diff. */
  function cellTable(result) {
    const cells = result.cells_changed || [];
    const isSheet = cells.length > 0 && "sheet" in cells[0];

    if (!cells.length) {
      return `
        <section class="card">
          <div class="card-head"><h3>Cell changes</h3></div>
          <div class="empty">
            <h4>No text cells were changed.</h4>
            <p>Numbers, IDs, dates and formulas are never rewritten.</p>
          </div>
        </section>`;
    }

    const rows = cells
      .map(
        (cell) => `
        <tr>
          <td class="cell-ref">${UI.esc(isSheet ? `${cell.sheet}!${cell.cell}` : `${cell.column} · row ${cell.row + 1}`)}</td>
          <td class="col-before">${UI.esc(cell.original)}</td>
          <td class="col-after">${UI.esc(cell.rewritten)}</td>
        </tr>`
      )
      .join("");

    return `
      <section class="card">
        <div class="card-head">
          <h3>Cell changes</h3>
          <p>${cells.length} text cell${cells.length === 1 ? "" : "s"} rewritten in a new file.</p>
        </div>
        <div class="table-wrap">
          <table class="data">
            <thead>
              <tr>
                <th>${isSheet ? "Sheet &amp; cell" : "Column &amp; row"}</th>
                <th>Original text</th>
                <th>Rewritten text</th>
              </tr>
            </thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
        <p class="table-note">
          Only natural-language cells appear here. Numeric values, IDs, dates and
          formulas were left exactly as they were, and the original file is unchanged.
        </p>
      </section>`;
  }

  /* ---------------------------- Public renderer ---------------------------- */
  /** Renders a full rewrite result (text, PDF, DOCX, CSV or XLSX) into `host`. */
  function render(host, result) {
    if (!host) return;
    const isTabular = result.input_type === "csv" || result.input_type === "xlsx";
    const changes = result.changes || { summary: {}, changes: [] };

    const actions = `
      <button class="btn btn-ghost btn-sm" data-goto-downloads type="button">Download results</button>`;

    host.innerHTML = `
      <div class="result-stack">
        ${UI.successPanel("Natural rewrite complete", actions)}
        ${isTabular ? cellTable(result) : beforeAfter(result)}
        ${summary(changes)}
        ${isTabular ? "" : changeReport(changes)}
        ${result.analysis
          ? `<section class="card">
               <div class="card-head">
                 <h3>Analysis of the original</h3>
                 <p>Run on the source content before rewriting.</p>
               </div>
               <div data-analysis-host></div>
             </section>`
          : ""}
        ${Downloads.card(result)}
      </div>`;

    if (result.analysis) {
      Analyzer.render(host.querySelector("[data-analysis-host]"), result);
    }
    bindResult(host, result);
  }

  function bindResult(host, result) {
    host.querySelectorAll("[data-copy]").forEach((button) => {
      button.addEventListener("click", () => {
        const which = button.dataset.copy;
        const source = host.querySelector(which === "original" ? "[data-original]" : "[data-rewritten]");
        UI.copy(source ? source.textContent : "", button);
      });
    });

    host.querySelectorAll(".change-head").forEach((head) => {
      head.addEventListener("click", () => {
        const card = head.closest(".change");
        const open = card.classList.toggle("is-open");
        head.setAttribute("aria-expanded", String(open));
      });
    });

    const expand = host.querySelector("[data-expand-all]");
    const collapse = host.querySelector("[data-collapse-all]");
    if (expand) {
      expand.addEventListener("click", () => {
        host.querySelectorAll(".change").forEach((card) => card.classList.add("is-open"));
        host.querySelectorAll(".change-head").forEach((h) => h.setAttribute("aria-expanded", "true"));
      });
    }
    if (collapse) {
      collapse.addEventListener("click", () => {
        host.querySelectorAll(".change").forEach((card) => card.classList.remove("is-open"));
        host.querySelectorAll(".change-head").forEach((h) => h.setAttribute("aria-expanded", "false"));
      });
    }

    const jump = host.querySelector("[data-goto-downloads]");
    if (jump) {
      jump.addEventListener("click", () => {
        const card = host.querySelector("[data-downloads-card]");
        if (card) card.scrollIntoView({ behavior: "smooth", block: "center" });
      });
    }
  }

  /* ---------------------------- Page wiring ---------------------------- */
  function init() {
    const input = UI.$("#rewriteInput");
    const host = UI.$("#rewriteResult");
    const runButton = UI.$("#rewriteRun");

    UI.empty(host, "No rewrite yet.",
             "Paste text above, or send content over from the Text Analyzer.");

    runButton.addEventListener("click", () => run(input.value, runButton, host));

    UI.$("#rewriteClear").addEventListener("click", () => {
      input.value = "";
      UI.empty(host, "No rewrite yet.",
               "Paste text above, or send content over from the Text Analyzer.");
    });

    input.addEventListener("keydown", (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key === "Enter") runButton.click();
    });
  }

  async function run(text, button, host) {
    if (!text || !text.trim()) {
      UI.toast("Nothing to rewrite", "Paste some text first.", "info");
      return;
    }
    UI.busy(button, true, "Rewriting…");
    UI.steps(
      host,
      ["Preparing content", "Analyzing the original", "Creating the natural rewrite", "Building the change report"],
      2,
      "Creating your natural rewrite"
    );

    const response = await Api.rewriteText(text, App.state.prefs.includeAnalysis);
    UI.busy(button, false);

    if (!response.ok) {
      UI.errorPanel(host, response.error, "Try again");
      const retry = host.querySelector("[data-retry]");
      if (retry) retry.addEventListener("click", () => run(text, button, host));
      UI.toast("Rewrite failed", Api.friendly(response.error), "error");
      return;
    }

    App.addJob(response, { kind: "text", label: "Pasted text", action: "rewrite" });
    render(host, response);
    UI.toast("Rewrite complete", "Review the change report below.", "ok");
  }

  return { init, render, run, cellTable, summary, changeReport };
})();

window.Rewriter = Rewriter;
