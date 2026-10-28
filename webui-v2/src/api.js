/**
 * Web UI V2 API Client
 * Consumes canonical backend endpoints via Vite dev proxy (/api -> http://127.0.0.1:8080)
 * BACKEND = SOURCE OF TRUTH / FRONTEND = PRESENTATION ONLY
 */

let isPromptingApiKey = false;

function resolveStoredApiKey() {
  if (typeof window === 'undefined') return '';
  return (
    window.__API_KEY__ ||
    (typeof sessionStorage !== 'undefined' && sessionStorage.getItem('api_key')) ||
    (typeof localStorage !== 'undefined' && localStorage.getItem('api_key')) ||
    ''
  );
}

// Sanitize URL immediately: if ?api_key= exists, store in sessionStorage and remove from URL
if (typeof window !== 'undefined' && window.location && window.location.search) {
  try {
    const url = new URL(window.location.href);
    const queryKey = url.searchParams.get('api_key');
    if (queryKey) {
      if (typeof sessionStorage !== 'undefined') {
        sessionStorage.setItem('api_key', queryKey);
      }
      url.searchParams.delete('api_key');
      const cleanUrl = url.pathname + (url.search || '') + (url.hash || '');
      window.history.replaceState({}, document.title, cleanUrl);
    }
  } catch {
    // Ignore URL sanitization error in non-standard environments
  }
}

async function fetchJson(endpoint, options = {}, isRetry = false) {
  const apiKey = resolveStoredApiKey();
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
    // If unauthorized (401) and in browser, prompt operator for key and retry once
    if (response.status === 401 && typeof window !== 'undefined' && !isRetry && !isPromptingApiKey) {
      isPromptingApiKey = true;
      try {
        const inputKey = window.prompt('Autenticação necessária. Digite a API Key da Video Factory:');
        if (inputKey && inputKey.trim()) {
          const cleanKey = inputKey.trim();
          if (typeof sessionStorage !== 'undefined') {
            sessionStorage.setItem('api_key', cleanKey);
          }
          isPromptingApiKey = false;
          return fetchJson(endpoint, options, true);
        }
      } catch {
        // window.prompt may be unavailable in some browser sandboxes
      } finally {
        isPromptingApiKey = false;
      }
    }

    let errorDetail = `HTTP ${response.status}: ${response.statusText}`;
    try {
      const body = await response.json();
      if (body.message) {
        errorDetail = typeof body.message === 'string' ? body.message : JSON.stringify(body.message);
      } else if (body.detail) {
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

export async function getChannelsOverview() {
  return fetchJson('/api/v2/channels');
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

export async function runFactoryCycle(options = {}) {
  const { profileId, channelId, force = true, oneShot = true } = options;
  const body = {};
  if (profileId) body.profile_id = profileId;
  if (channelId) body.channel_id = channelId;
  body.force = force;
  body.one_shot = oneShot;

  return fetchJson('/api/v2/factory/run-cycle', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  });
}

export async function updateProfileGrowthMode(profileId, growthMode) {
  if (!profileId) throw new Error('profileId é obrigatório');
  return fetchJson(`/api/v2/channels/${encodeURIComponent(profileId)}/growth-mode`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ growth_mode: growthMode }),
  });
}

export async function updateProfileAutonomousMode(profileId, enabled) {
  if (!profileId) throw new Error('profileId é obrigatório');
  return fetchJson(`/api/v2/channels/${encodeURIComponent(profileId)}/autonomous`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ enabled: Boolean(enabled) }),
  });
}

export async function getProfileSettings(profileId) {
  if (!profileId) throw new Error('profileId é obrigatório');
  return fetchJson(`/api/v2/channels/${encodeURIComponent(profileId)}/settings`);
}

export async function updateProfileQuotas(profileId, quotas) {
  if (!profileId) throw new Error('profileId é obrigatório');
  return fetchJson(`/api/v2/channels/${encodeURIComponent(profileId)}/quotas`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(quotas),
  });
}

export async function updateProfileSchedule(profileId, schedule) {
  if (!profileId) throw new Error('profileId é obrigatório');
  return fetchJson(`/api/v2/channels/${encodeURIComponent(profileId)}/schedule`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(schedule),
  });
}

export async function updateProfileVoice(profileId, voiceSettings) {
  if (!profileId) throw new Error('profileId é obrigatório');
  return fetchJson(`/api/v2/channels/${encodeURIComponent(profileId)}/voice`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(voiceSettings),
  });
}

export async function getAllowedVoices() {
  return fetchJson('/api/v2/voices/allowed');
}

export async function getHealth() {
  return fetchJson('/api/v2/health');
}

export function setApiKey(key) {
  if (typeof sessionStorage !== 'undefined') {
    if (key) {
      sessionStorage.setItem('api_key', key);
    } else {
      sessionStorage.removeItem('api_key');
    }
  }
}

export function getStoredApiKey() {
  return resolveStoredApiKey();
}

export async function getReviewTasks(filter = 'pending', profileId = null) {
  const params = new URLSearchParams();
  if (filter) params.set('filter', filter);
  if (profileId) params.set('profile_id', profileId);
  const qs = params.toString() ? `?${params.toString()}` : '';
  return fetchJson(`/api/v2/review/tasks${qs}`);
}

export function getReviewTaskVideoUrl(taskId) {
  if (!taskId) return '';
  const apiKey = resolveStoredApiKey();
  const query = apiKey ? `?api_key=${encodeURIComponent(apiKey)}` : '';
  return `/api/v2/review/tasks/${encodeURIComponent(taskId)}/video${query}`;
}

export async function approveReviewTask(taskId, options = {}) {
  const { operatorId = 'operator', note = '', confirm = 'APPROVE_FOR_STOCK' } = options;
  return fetchJson(`/api/v2/review/tasks/${encodeURIComponent(taskId)}/approve`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      operator_id: operatorId,
      note,
      confirm,
    }),
  });
}

export async function discardReviewTask(taskId, options = {}) {
  const { operatorId = 'operator', note = '', confirm = 'DISCARD_HELD_VIDEO' } = options;
  return fetchJson(`/api/v2/review/tasks/${encodeURIComponent(taskId)}/discard`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      operator_id: operatorId,
      note,
      confirm,
    }),
  });
}




/**
 * GET /api/v2/fleet/summary — Central Fleet aggregated summary & channels health.
 */
export async function getFleetSummary() {
  return fetchJson('/api/v2/fleet/summary');
}


/**
 * GET /api/v2/production/overview — Resumo operacional de produção V2.
 */
export async function getProductionOverview(profileId = null, limitPerSection = null) {
  const params = new URLSearchParams();
  if (profileId) params.set('profile_id', profileId);
  if (limitPerSection != null) params.set('limit_per_section', String(limitPerSection));
  const qs = params.toString() ? `?${params.toString()}` : '';
  return fetchJson(`/api/v2/production/overview${qs}`);
}

/**
 * GET /api/v2/diagnostics/overview — Diagnóstico de produção V2 (Missão SIS3).
 */
export async function getDiagnosticsOverview(profileId = null) {
  const params = new URLSearchParams();
  if (profileId) params.set('profile_id', profileId);
  const qs = params.toString() ? `?${params.toString()}` : '';
  return fetchJson(`/api/v2/diagnostics/overview${qs}`);
}
