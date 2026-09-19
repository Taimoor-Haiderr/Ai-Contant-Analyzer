/* ==========================================================================
   uploader.js - drag & drop, upload progress and the document workflow.

   Progress reflects real states: upload percentage comes from the XHR upload
   event, and the step list advances only when a stage actually starts.
   ========================================================================== */

const Uploader = (() => {

  const KIND_LABEL = {
    pdf: "PDF", docx: "DOCX", csv: "CSV", xlsx: "XLSX", text: "TXT",
  };

  let busy = false;   // prevents duplicate submissions while processing

  /* ---------------------------- Dropzone wiring ---------------------------- */
  function bindDropzone(zone, fileInput, onFile) {
    if (!zone || !fileInput) return;

    zone.addEventListener("click", () => fileInput.click());
    zone.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        fileInput.click();
      }
    });

    ["dragenter", "dragover"].forEach((name) =>
      zone.addEventListener(name, (event) => {
        event.preventDefault();
        zone.classList.add("is-over");
      })
    );
    ["dragleave", "drop"].forEach((name) =>
      zone.addEventListener(name, (event) => {
        event.preventDefault();
        if (name === "dragleave" && zone.contains(event.relatedTarget)) return;
        zone.classList.remove("is-over");
      })
    );

    zone.addEventListener("drop", (event) => {
      const file = event.dataTransfer && event.dataTransfer.files[0];
      if (file) onFile(file);
    });

    fileInput.addEventListener("change", () => {
      if (fileInput.files[0]) onFile(fileInput.files[0]);
      fileInput.value = "";        // allow re-selecting the same file
    });
  }

  /* ---------------------------- File header card ---------------------------- */
  function fileHeader(meta, statusHtml) {
    return `
      <div class="file-head">
        <span class="list-icon">${UI.esc(KIND_LABEL[meta.kind] || "FILE")}</span>
        <div class="list-main">
          <strong>${UI.esc(meta.name)}</strong>
          <div class="sub">${UI.esc(meta.extension)} · ${UI.bytes(meta.size)}</div>
        </div>
        <div>${statusHtml || ""}</div>
      </div>`;
  }

  /* ---------------------------- Main workflow ---------------------------- */
  /**
   * Uploads a file, then runs either analysis or a rewrite on it.
   * `mode` is "analyze" or "rewrite".
   */
  async function process(file, host, mode) {
    if (busy) {
      UI.toast("Already working", "Please wait for the current file to finish.", "info");
      return;
    }
    busy = true;

    const stages =
      mode === "rewrite"
        ? ["Uploading file", "Extracting text", "Analyzing content", "Creating the natural rewrite", "Preparing result"]
        : ["Uploading file", "Extracting text", "Analyzing content", "Preparing report"];

    UI.steps(host, stages, 0, `Processing ${file.name}`);

    // --- 1. upload (real percentage from the browser) ---
    const uploaded = await Api.upload(file, (percent) => {
      const first = host.querySelector(".step span:last-child");
      if (first) first.textContent = `Uploading file — ${percent}%`;
    });

    if (!uploaded.ok) {
      busy = false;
      showError(host, uploaded.error, file, mode);
      return;
    }

    currentFileId = uploaded.file_id;

    // --- 2. extraction + analysis happen server-side in one call ---
    UI.steps(host, stages, mode === "rewrite" ? 2 : 2, `Processing ${file.name}`);

    const response =
      mode === "rewrite"
        ? await Api.rewriteFile(uploaded.file_id, App.state.prefs.includeAnalysis)
        : await Api.analyzeFile(uploaded.file_id);

    busy = false;

    if (!response.ok) {
      showError(host, response.error, file, mode);
      return;
    }

    App.addJob(response, {
      kind: uploaded.kind,
      label: uploaded.name,
      action: mode === "rewrite" ? "rewrite" : "analysis",
    });

    renderResult(host, response, uploaded, mode);
    UI.toast(
      mode === "rewrite" ? "Rewrite complete" : "Analysis complete",
      `${uploaded.name} processed successfully.`,
      "ok"
    );
  }

  function showError(host, error, file, mode) {
    UI.errorPanel(host, error, "Try again");
    const retry = host.querySelector("[data-retry]");
    if (retry) retry.addEventListener("click", () => process(file, host, mode));
    UI.toast("Couldn't process file", Api.friendly(error), "error");
  }

  /* ---------------------------- Result rendering ---------------------------- */
  function renderResult(host, result, meta, mode) {
    const isTabular = result.input_type === "csv" || result.input_type === "xlsx";

    if (mode === "rewrite") {
      host.innerHTML = `<div class="card">${fileHeader(meta,
        `<span class="badge badge-low">Rewritten</span>`)}
        <p class="muted" style="font-size:13.5px">
          The original file was not modified. The rewrite was written to a new file.
        </p></div>
        <div id="docRewriteHost"></div>`;
      Rewriter.render(UI.$("#docRewriteHost"), result);
      return;
    }

    const mapping = UI.indication(result.analysis && result.analysis.ai_likelihood);
    host.innerHTML = `
      <div class="card">
        ${fileHeader(meta, `<span class="badge ${mapping.cls}">${UI.esc(
          (result.analysis && result.analysis.ai_likelihood) || "Inconclusive"
        )}</span>`)}
        ${UI.successPanel("Analysis complete", `
          <button class="btn btn-primary btn-sm" data-rewrite-file type="button">Create Natural Rewrite</button>`)}
        <div style="margin-top:20px" data-analysis-host></div>
      </div>
      ${isTabular ? `<section class="card">
          <div class="card-head">
            <h3>Detected content</h3>
            <p>Only natural-language cells are analyzed. Numbers, IDs, dates and
               formulas are ignored and never modified.</p>
          </div>
          ${metaTable(result)}
        </section>` : ""}
      ${Downloads.card(result)}`;

    Analyzer.render(host.querySelector("[data-analysis-host]"), result);

    const rewriteButton = host.querySelector("[data-rewrite-file]");
    if (rewriteButton) {
      rewriteButton.addEventListener("click", async () => {
        UI.busy(rewriteButton, true, "Rewriting…");
        const response = await Api.rewriteFile(
          currentFileId || "", App.state.prefs.includeAnalysis
        );
        UI.busy(rewriteButton, false);
        if (!response.ok) {
          UI.toast("Rewrite failed", Api.friendly(response.error), "error");
          return;
        }
        App.addJob(response, { kind: meta.kind, label: meta.name, action: "rewrite" });
        renderResult(host, response, meta, "rewrite");
        UI.toast("Rewrite complete", "Review the change report below.", "ok");
      });
    }
  }

  /** Small metadata table for spreadsheets and CSV files. */
  function metaTable(result) {
    const info = (result.extraction && result.extraction.metadata) || {};
    const rows = [];

    if (info.columns) {
      rows.push(["Columns", info.columns.join(", ")]);
      rows.push(["Text columns", (info.text_columns || []).join(", ") || "none detected"]);
      rows.push(["Rows", info.row_count]);
    }
    if (info.sheets) {
      rows.push(["Sheets", info.sheets.map((s) => s.sheet).join(", ")]);
      rows.push(["Formula cells", info.formula_cells]);
    }
    if (info.rewritable_cells !== undefined) {
      rows.push(["Text cells found", info.rewritable_cells]);
    }

    if (!rows.length) return "";
    return `
      <div class="table-wrap">
        <table class="data">
          <tbody>
            ${rows.map(([key, value]) =>
              `<tr><td style="width:190px;color:var(--text-2)">${UI.esc(key)}</td>
                   <td>${UI.esc(value)}</td></tr>`).join("")}
          </tbody>
        </table>
      </div>`;
  }

  /* ---------------------------- Page wiring ---------------------------- */
  let currentFileId = null;

  function init() {
    const docHost = UI.$("#docResult");
    UI.empty(docHost, "No document yet.", "Upload a PDF, DOCX, XLSX, CSV or TXT file to get started.");

    bindDropzone(UI.$("#docDrop"), UI.$("#docFile"), async (file) => {
      const uploadedMeta = await handleDocument(file, docHost);
      currentFileId = uploadedMeta;
    });

    // Dashboard quick-analyze dropzone shares the same workflow.
    bindDropzone(UI.$("#quickDrop"), UI.$("#quickFile"), (file) => {
      App.go("documents");
      handleDocument(file, docHost);
    });
  }

  async function handleDocument(file, host) {
    // Keep the file id around so "Create Natural Rewrite" can reuse the upload.
    const stages = ["Uploading file", "Extracting text", "Analyzing content", "Preparing report"];
    if (busy) {
      UI.toast("Already working", "Please wait for the current file to finish.", "info");
      return null;
    }
    busy = true;
    UI.steps(host, stages, 0, `Processing ${file.name}`);

    const uploaded = await Api.upload(file, (percent) => {
      const label = host.querySelector(".step span:last-child");
      if (label) label.textContent = `Uploading file — ${percent}%`;
    });

    if (!uploaded.ok) {
      busy = false;
      showError(host, uploaded.error, file, "analyze");
      return null;
    }

    currentFileId = uploaded.file_id;
    UI.steps(host, stages, 2, `Processing ${file.name}`);

    const response = await Api.analyzeFile(uploaded.file_id);
    busy = false;

    if (!response.ok) {
      showError(host, response.error, file, "analyze");
      return null;
    }

    App.addJob(response, { kind: uploaded.kind, label: uploaded.name, action: "analysis" });
    renderResult(host, response, uploaded, "analyze");
    UI.toast("Analysis complete", `${uploaded.name} analyzed successfully.`, "ok");
    return uploaded.file_id;
  }

  return { init, process, bindDropzone };
})();

window.Uploader = Uploader;
