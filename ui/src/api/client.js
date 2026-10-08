/**
 * API client communicating with the Round 3 orchestrator HTTP front door.
 * All requests route through the Vite proxy (/api -> http://127.0.0.1:8100).
 *
 * Endpoint references:
 * - GET  /health                  orchestration/api.py:29-39
 * - POST /workflows               orchestration/api.py:42-49
 * - GET  /workflows/{id}          orchestration/api.py:59-62
 * - GET  /workflows/{id}/evidence orchestration/api.py:64-66
 * - POST /workflows/{id}/resume   orchestration/api.py:69-72
 * - POST /workflows/{id}/overrides orchestration/api.py:75-82
 */

async function request(path, options = {}) {
  const url = `/api${path}`
  const headers = {
    'Content-Type': 'application/json',
    ...(options.headers || {}),
  }

  let res
  try {
    res = await fetch(url, { ...options, headers })
  } catch (err) {
    throw new Error(`Network failure connecting to orchestrator at ${url}: ${err.message}`)
  }

  let data = null
  const text = await res.text()
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = { raw: text }
    }
  }

  if (!res.ok) {
    const errorMsg = data?.detail || data?.message || (typeof data?.raw === 'string' ? data.raw : `HTTP ${res.status}`)
    const err = new Error(errorMsg)
    err.status = res.status
    err.data = data
    throw err
  }

  return data
}


/** Run or advance a workflow case (orchestration/api.py:42-49) */
export async function createWorkflow({ org_id, unit_id, route, returned }) {
  const body = { org_id, unit_id }
  if (route && route !== 'auto') {
    body.route = route
  }
  if (typeof returned === 'boolean') {
    body.returned = returned
  }
  return request('/workflows', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

/** Fetch workflow state by ID (orchestration/api.py:59-62) */
export async function getWorkflow(workflowId) {
  return request(`/workflows/${encodeURIComponent(workflowId)}`)
}

/** Fetch workflow state and all referenced evidence records (orchestration/api.py:64-66) */
export async function getWorkflowEvidence(workflowId) {
  return request(`/workflows/${encodeURIComponent(workflowId)}/evidence`)
}

/** Resume workflow after halt, override, or failure (orchestration/api.py:69-72) */
export async function resumeWorkflow(workflowId) {
  return request(`/workflows/${encodeURIComponent(workflowId)}/resume`, {
    method: 'POST',
    body: JSON.stringify({}),
  })
}

/** Apply an override to an evidence record's decision (orchestration/api.py:75-82) */
export async function applyOverride(workflowId, { record_id, new_verdict, actor, reason, new_outcome }) {
  const body = {
    record_id,
    new_verdict,
    actor,
    reason,
  }
  if (new_outcome) {
    body.new_outcome = new_outcome
  }
  return request(`/workflows/${encodeURIComponent(workflowId)}/overrides`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}
