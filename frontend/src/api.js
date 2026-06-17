// Central place for backend URLs. Override at build time with VITE_API_URL.
export const API_BASE =
  import.meta.env.VITE_API_URL || "http://localhost:8000";

export const WS_BASE = API_BASE.replace(/^http/, "ws");

// Read the JWT the auth layer stored, so authenticated requests can replay it.
function authHeaders(extra = {}) {
  const token = localStorage.getItem("deepfield_token");
  return token ? { ...extra, Authorization: `Bearer ${token}` } : extra;
}

export async function createReport(query, opts = {}) {
  const res = await fetch(`${API_BASE}/reports`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({
      query,
      mode: opts.mode ?? "deep",
      source_scope: opts.sourceScope ?? "web",
      thread_id: opts.threadId ?? null,
      parent_report_id: opts.parentReportId ?? null,
      context: opts.context ?? null,
      year_min: opts.yearMin ?? null,
      include_domains: opts.includeDomains ?? null,
      exclude_domains: opts.excludeDomains ?? null,
    }),
  });
  if (res.status === 401) {
    const err = new Error("Please sign in to run research.");
    err.code = 401;
    throw err;
  }
  if (res.status === 429) {
    // Usage cap reached (per-user monthly or global daily). Surface the
    // backend's message and flag it so the UI shows a neutral notice.
    let detail = "You've reached your deep-research limit. Please try again later.";
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* ignore */
    }
    const err = new Error(detail);
    err.code = 429;
    err.limited = true;
    throw err;
  }
  if (!res.ok) throw new Error(`createReport failed: ${res.status}`);
  return res.json();
}

export async function getUsage() {
  const res = await fetch(`${API_BASE}/usage`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`getUsage failed: ${res.status}`);
  return res.json();
}

export async function listThreads() {
  // History is per-account, so this is an authenticated request.
  const res = await fetch(`${API_BASE}/threads`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`listThreads failed: ${res.status}`);
  return res.json();
}

export async function getThread(id) {
  const res = await fetch(`${API_BASE}/threads/${id}`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`getThread failed: ${res.status}`);
  return res.json();
}

export async function getReport(id) {
  const res = await fetch(`${API_BASE}/reports/${id}`);
  if (!res.ok) throw new Error(`getReport failed: ${res.status}`);
  return res.json();
}

export async function getSources(id) {
  const res = await fetch(`${API_BASE}/reports/${id}/sources`);
  if (!res.ok) throw new Error(`getSources failed: ${res.status}`);
  return res.json();
}

export async function getConflicts(id) {
  const res = await fetch(`${API_BASE}/reports/${id}/conflicts`);
  if (!res.ok) throw new Error(`getConflicts failed: ${res.status}`);
  return res.json();
}

export async function getGaps(id) {
  const res = await fetch(`${API_BASE}/reports/${id}/gaps`);
  if (!res.ok) throw new Error(`getGaps failed: ${res.status}`);
  return res.json();
}

// ---- Disagreement graph (read-only explorer) ----

export async function getGraphStats() {
  const res = await fetch(`${API_BASE}/graph/stats`);
  if (!res.ok) throw new Error(`getGraphStats failed: ${res.status}`);
  return res.json();
}

export async function getDisagreements(limit = 30) {
  const res = await fetch(`${API_BASE}/graph/disagreements?limit=${limit}`);
  if (!res.ok) throw new Error(`getDisagreements failed: ${res.status}`);
  return res.json();
}

export async function getClaim(id) {
  const res = await fetch(`${API_BASE}/graph/claims/${id}`);
  if (!res.ok) throw new Error(`getClaim failed: ${res.status}`);
  return res.json();
}

export async function searchGraph(q, limit = 20) {
  const res = await fetch(
    `${API_BASE}/graph/search?q=${encodeURIComponent(q)}&limit=${limit}`
  );
  if (!res.ok) throw new Error(`searchGraph failed: ${res.status}`);
  return res.json();
}

// ---- Citations, compare, comments, PDF upload ----

export async function getCitations(id, format = "apa") {
  const res = await fetch(`${API_BASE}/reports/${id}/citations?format=${format}`);
  if (!res.ok) throw new Error(`getCitations failed: ${res.status}`);
  return res.json();
}

export async function compareSources(sourceAId, sourceBId) {
  const res = await fetch(`${API_BASE}/compare`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_a_id: sourceAId, source_b_id: sourceBId }),
  });
  if (!res.ok) throw new Error(`compareSources failed: ${res.status}`);
  return res.json();
}

export async function getComments(id) {
  const res = await fetch(`${API_BASE}/reports/${id}/comments`);
  if (!res.ok) throw new Error(`getComments failed: ${res.status}`);
  return res.json();
}

export async function addComment(id, { author, body, anchor, assignedTo } = {}) {
  const res = await fetch(`${API_BASE}/reports/${id}/comments`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      author: author || "Anonymous",
      body,
      anchor: anchor ?? null,
      assigned_to: assignedTo ?? null,
    }),
  });
  if (!res.ok) throw new Error(`addComment failed: ${res.status}`);
  return res.json();
}

export async function patchComment(commentId, patch = {}) {
  const res = await fetch(`${API_BASE}/comments/${commentId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      resolved: patch.resolved ?? null,
      assigned_to: patch.assignedTo ?? null,
    }),
  });
  if (!res.ok) throw new Error(`patchComment failed: ${res.status}`);
  return res.json();
}

export async function uploadPaper(id, file) {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/reports/${id}/papers`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(`uploadPaper failed: ${res.status}`);
  return res.json();
}

// ---- Auth ----

// Pull a friendly message out of FastAPI's {detail: "..."} error envelope.
async function _authError(res, fallback) {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return new Error(body.detail);
    if (Array.isArray(body?.detail) && body.detail[0]?.msg)
      return new Error(body.detail[0].msg);
  } catch {
    /* non-JSON body */
  }
  return new Error(fallback);
}

export async function signup({ email, password, name } = {}) {
  const res = await fetch(`${API_BASE}/auth/signup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, name: name || null }),
  });
  if (!res.ok) throw await _authError(res, "Could not create account");
  return res.json();
}

export async function login({ email, password } = {}) {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw await _authError(res, "Could not sign in");
  return res.json();
}

export async function getMe(token) {
  const res = await fetch(`${API_BASE}/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw await _authError(res, "Session expired");
  return res.json();
}
