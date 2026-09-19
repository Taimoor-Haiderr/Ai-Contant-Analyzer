/* ==========================================================================
   app.js - routing, session state and start-up.

   Session state lives in memory plus sessionStorage. There is no database and
   no account system: closing the tab ends the session, and the UI says so.
   ========================================================================== */

const App = (() => {

  const PAGES = {
    dashboard: ["Dashboard", "Analyze content, understand it, improve it naturally."],
    analyzer: ["Text Analyzer", "Paste content and review its linguistic indicators."],
    documents: ["Documents", "Upload PDF, DOCX, XLSX, CSV or TXT files."],
    rewrite: ["Natural Rewrite", "Improve clarity and flow while preserving meaning."],
    reports: ["Reports", "Files generated during this session."],
    history: ["History", "Results from this browser session."],
    settings: ["Settings", "Engine status and local preferences."],
  };

  const STORAGE_KEY = "aca.session.v1";

  const state = {
    route: "dashboard",
    jobs: [],                 // newest first
    health: null,
    prefs: { formats: ["txt", "json", "html"], includeAnalysis: true },
  };

  /* ---------------------------- Session storage ---------------------------- */
  function saveSession() {
    try {
      sessionStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ jobs: state.jobs, prefs: state.prefs })
      );
    } catch (err) {
      /* Storage can be unavailable or full; the app works without it. */
    }
  }

  function loadSession() {
    try {
      const raw = sessionStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed.jobs)) state.jobs = parsed.jobs;
      if (parsed.prefs) Object.assign(state.prefs, parsed.prefs);
    } catch (err) {
      state.jobs = [];
    }
  }

  function addJob(result, meta) {
    const job = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      jobId: result.job_id || "",
      kind: meta.kind || "text",
      label: meta.label || "Untitled",
      action: meta.action || "analysis",
      createdAt: new Date().toISOString(),
      downloads: result.downloads || [],
      result,
    };
    state.jobs.unshift(job);
    if (state.jobs.length > 25) state.jobs.length = 25;   // keep storage small
    saveSession();
    Dashboard.refresh();
    Reports.refresh();
    return job;
  }

  function findJob(jobId) {
    return state.jobs.find((job) => job.jobId === jobId);
  }

  async function clearSession() {
    state.jobs = [];
    saveSession();
    await Api.clearSession();
    Dashboard.refresh();
    Reports.refresh();
    UI.toast("Session cleared", "All results from this session were removed.", "ok");
  }

  /* ---------------------------- Routing ---------------------------- */
  function go(route) {
    if (!PAGES[route]) route = "dashboard";
    state.route = route;

    UI.$$(".page").forEach((page) => {
      const active = page.id === `page-${route}`;
      page.classList.toggle("is-active", active);
      page.hidden = !active;
    });

    UI.$$(".nav-item").forEach((item) =>
      item.classList.toggle("is-active", item.dataset.route === route)
    );

    const [title, subtitle] = PAGES[route];
    UI.$("#pageTitle").textContent = title;
    UI.$("#pageSubtitle").textContent = subtitle;
    document.title = `${title} · AI Content Analyzer`;

    if (window.location.hash !== `#${route}`) {
      window.history.replaceState(null, "", `#${route}`);
    }
    closeSidebar();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  /* ---------------------------- Sidebar (mobile) ---------------------------- */
  function openSidebar() {
    UI.$("#sidebar").classList.add("is-open");
    UI.$("#sidebarScrim").hidden = false;
    UI.$("#menuBtn").setAttribute("aria-expanded", "true");
  }

  function closeSidebar() {
    UI.$("#sidebar").classList.remove("is-open");
    UI.$("#sidebarScrim").hidden = true;
    UI.$("#menuBtn").setAttribute("aria-expanded", "false");
  }

  /* ---------------------------- Engine health ---------------------------- */
  async function checkHealth() {
    const health = await Api.health();
    state.health = health;

    const dot = UI.$("#statusDot");
    const text = UI.$("#statusText");

    if (!health.ok) {
      dot.className = "dot dot-bad";
      text.textContent = "Engine offline";
      UI.$("#settingsInfo").innerHTML =
        `<dt>Status</dt><dd>Not reachable — start the Python server with <code>python server.py</code></dd>`;
      UI.$("#uploadLimits").textContent = "Engine offline — start the Python server to upload files.";
      return;
    }

    const offline = health.mode === "mock";
    dot.className = `dot ${offline ? "dot-warn" : "dot-ok"}`;
    text.textContent = offline ? "Offline test mode" : "Engine connected";

    UI.$("#uploadLimits").textContent =
      `Supported: ${health.supported_extensions.join(", ")} · Maximum ${health.max_upload_mb} MB per file.`;

    UI.$("#settingsInfo").innerHTML = `
      <dt>Engine</dt><dd>${UI.esc(health.engine)}</dd>
      <dt>Mode</dt><dd>${offline ? "Offline test mode (local heuristics)" : "Connected to a model"}</dd>
      <dt>Provider</dt><dd>${UI.esc(health.provider)}</dd>
      <dt>Model name</dt><dd>${UI.esc(health.model_name || "not set")}</dd>
      <dt>API key</dt><dd>${health.api_key_configured
        ? "Configured in the Python environment (never sent to this page)"
        : "Not configured"}</dd>
      <dt>Max upload</dt><dd>${UI.esc(health.max_upload_mb)} MB</dd>
      <dt>Chunk size</dt><dd>${UI.esc(health.max_chunk_chars)} characters</dd>
      <dt>Supported files</dt><dd>${UI.esc(health.supported_extensions.join(", "))}</dd>`;

    if (offline) {
      UI.toast(
        "Offline test mode",
        "Results come from local heuristics. Add MODEL_API_KEY to .env for real analysis.",
        "info"
      );
    }
  }

  /* ---------------------------- Preferences ---------------------------- */
  function initPrefs() {
    const boxes = UI.$$("#formatPrefs input");
    boxes.forEach((box) => {
      box.checked = state.prefs.formats.includes(box.value);
      box.addEventListener("change", () => {
        state.prefs.formats = boxes.filter((b) => b.checked).map((b) => b.value);
        if (!state.prefs.formats.length) {
          state.prefs.formats = ["json"];
          UI.toast("At least one format", "JSON was kept selected.", "info");
          boxes.find((b) => b.value === "json").checked = true;
        }
        saveSession();
      });
    });

    const analysisToggle = UI.$("#prefAnalysis");
    analysisToggle.checked = state.prefs.includeAnalysis;
    analysisToggle.addEventListener("change", () => {
      state.prefs.includeAnalysis = analysisToggle.checked;
      saveSession();
    });

    UI.$("#clearSession").addEventListener("click", clearSession);
  }

  /* ---------------------------- Global wiring ---------------------------- */
  function bindGlobal() {
    document.addEventListener("click", (event) => {
      const routeButton = event.target.closest("[data-route]");
      if (routeButton) {
        go(routeButton.dataset.route);
        return;
      }
      if (event.target.closest("[data-close]")) UI.closeModal();
    });

    UI.$("#menuBtn").addEventListener("click", () => {
      const open = UI.$("#sidebar").classList.contains("is-open");
      open ? closeSidebar() : openSidebar();
    });
    UI.$("#sidebarScrim").addEventListener("click", closeSidebar);

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        UI.closeModal();
        closeSidebar();
      }
    });

    window.addEventListener("hashchange", () => {
      go((window.location.hash || "#dashboard").slice(1));
    });
  }

  /* ---------------------------- Boot ---------------------------- */
  function init() {
    loadSession();
    bindGlobal();
    initPrefs();

    Dashboard.init();
    Analyzer.init();
    Rewriter.init();
    Uploader.init();
    Reports.init();
    Downloads.bind();

    go((window.location.hash || "#dashboard").slice(1));
    checkHealth();
  }

  return { state, init, go, addJob, findJob, saveSession, clearSession, checkHealth };
})();

window.App = App;
document.addEventListener("DOMContentLoaded", App.init);
