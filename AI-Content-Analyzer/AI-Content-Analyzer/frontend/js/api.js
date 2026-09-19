/* ==========================================================================
   api.js - every call to the Python backend goes through here.
   Change API_BASE_URL alone to point the dashboard at a different host.
   The provider API key lives only in the Python .env and is never sent here.
   ========================================================================== */

const API_BASE_URL = window.API_BASE_URL || "";

const Api = (() => {

  /** Friendly wording for backend error codes. */
  const MESSAGES = {
    missing_api_key:
      "No model is connected yet. Add MODEL_API_KEY to the .env file, or set TEST_MODE=true to run the offline engine.",
    provider_timeout:
      "The model took too long to respond. Please try again in a moment.",
    provider_error:
      "The AI service is temporarily unavailable. Please try again later.",
    context_limit:
      "That request was too large for the model. Lower MAX_CHUNK_CHARS in .env and try again.",
    invalid_model_response:
      "The model returned an unusable response. Please try again.",
    scanned_document:
      "This PDF looks like a scan. It contains images rather than selectable text, so there is nothing to analyze. Run OCR on it first, then upload the result.",
    corrupt_file:
      "We couldn't read this file. Please check that it opens correctly and try again.",
    unsupported_file_type:
      "That file type isn't supported. Use PDF, DOCX, XLSX, CSV or TXT.",
    empty_content: "There's no readable text in that input.",
    file_too_large: "That file is larger than the upload limit.",
    file_not_found: "That file is no longer available. Please upload it again.",
    job_not_found: "That result is no longer in this session. Please run it again.",
    extraction_failed: "We couldn't extract any text from this file.",
    server_error: "Something went wrong on the server. Please try again.",
    network_error:
      "Can't reach the Python engine. Make sure the server is running, then try again.",
  };

  function friendly(error) {
    if (!error) return MESSAGES.server_error;
    return MESSAGES[error.code] || error.message || MESSAGES.server_error;
  }

  async function request(path, options = {}) {
    let response;
    try {
      response = await fetch(API_BASE_URL + path, options);
    } catch (networkError) {
      return {
        ok: false,
        error: { code: "network_error", message: MESSAGES.network_error },
      };
    }

    let data;
    try {
      data = await response.json();
    } catch (parseError) {
      return {
        ok: false,
        error: { code: "server_error", message: MESSAGES.server_error },
      };
    }
    return data;
  }

  function postJson(path, body) {
    return request(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
  }

  return {
    baseUrl: API_BASE_URL,
    friendly,

    health: () => request("/api/health"),

    analyzeText: (text) => postJson("/api/analyze/text", { text }),

    rewriteText: (text, includeAnalysis) =>
      postJson("/api/rewrite/text", { text, include_analysis: includeAnalysis !== false }),

    analyzeFile: (fileId) => postJson("/api/analyze/file", { file_id: fileId }),

    rewriteFile: (fileId, includeAnalysis) =>
      postJson("/api/rewrite/file", {
        file_id: fileId,
        include_analysis: includeAnalysis !== false,
      }),

    exportJob: (jobId, formats) => postJson(`/api/export/${jobId}`, { formats }),

    clearSession: () => postJson("/api/session/clear", {}),

    downloadUrl: (token) => `${API_BASE_URL}/api/download/${token}`,

    /** Uploads report real progress via the XHR upload event. */
    upload(file, onProgress) {
      return new Promise((resolve) => {
        const form = new FormData();
        form.append("file", file);

        const xhr = new XMLHttpRequest();
        xhr.open("POST", API_BASE_URL + "/api/upload");

        if (typeof onProgress === "function" && xhr.upload) {
          xhr.upload.onprogress = (event) => {
            if (event.lengthComputable) {
              onProgress(Math.round((event.loaded / event.total) * 100));
            }
          };
        }

        xhr.onload = () => {
          try {
            resolve(JSON.parse(xhr.responseText));
          } catch (err) {
            resolve({
              ok: false,
              error: { code: "server_error", message: MESSAGES.server_error },
            });
          }
        };
        xhr.onerror = () =>
          resolve({
            ok: false,
            error: { code: "network_error", message: MESSAGES.network_error },
          });

        xhr.send(form);
      });
    },
  };
})();

window.Api = Api;
