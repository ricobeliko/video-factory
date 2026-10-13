/**
 * Web UI V2 API Client
 * Consumes canonical backend endpoints via Vite dev proxy (/api -> http://127.0.0.1:8080)
 * BACKEND = SOURCE OF TRUTH / FRONTEND = PRESENTATION ONLY
 */

async function fetchJson(endpoint, options = {}) {
  const apiKey = typeof window !== 'undefined'
    ? (window.__API_KEY__ || localStorage.getItem('api_key') || sessionStorage.getItem('api_key') || '')
    : '';
  const authHeaders = apiKey ? { 'x-api-key': apiKey } : {};

  const response = await fetch(endpoint, {
    headers: {
      'Accept': 'application/json',
      ...authHeaders,
      ...options.headers,
    },
    ...options,
  });

  if (!response.ok) {
    let errorDetail = `HTTP ${response.status}: ${response.statusText}`;
    try {
      const body = await response.json();
      if (body.detail) {
        errorDetail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
      }
    } catch {
      // Non-JSON response
    }
    const err = new Error(errorDetail);
    err.status = response.status;
    throw err;
  }

  const payload = await response.json();
  if (payload && typeof payload === 'object' && payload.data !== undefined && payload.status === 200) {
    return payload.data;
  }
  return payload;
}

export async function getLiveExecutions() {
  return fetchJson('/api/v2/executions/live');
}

export async function getExecutionDetail(taskId) {
  if (!taskId) return null;
  return fetchJson(`/api/v2/executions/${encodeURIComponent(taskId)}`);
}

export async function getSystemStatus(profileId = null) {
  const query = profileId ? `?profile_id=${encodeURIComponent(profileId)}` : '';
  return fetchJson(`/api/v2/system/status${query}`);
}

export async function getProfiles() {
  return fetchJson('/api/v2/profiles');
}

export async function getProfileStatus(profileId) {
  return fetchJson(`/api/v2/profiles/${encodeURIComponent(profileId)}/status`);
}

export async function getSchedulerPosts(limit = 10, profileId = null) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (profileId) params.set('profile_id', profileId);
  return fetchJson(`/api/v2/scheduler/posts?${params.toString()}`);
}

export async function getPublications(limit = 10, profileId = null) {
  const params = new URLSearchParams({ limit: String(limit) });
  if (profileId) params.set('profile_id', profileId);
  return fetchJson(`/api/v2/publications?${params.toString()}`);
}

export async function getProviderHealth() {
  return fetchJson('/api/v2/providers/health');
}

export async function getAgentOps() {
  return fetchJson('/api/v2/agent-ops');
}

export async function pauseFactory() {
  return fetchJson('/api/v2/factory/pause', {
    method: 'POST',
  });
}

export async function resumeFactory() {
  return fetchJson('/api/v2/factory/resume', {
    method: 'POST',
  });
}
