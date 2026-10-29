/**
 * Pure business and presentation logic for the Fleet screen (webui-v2).
 * Strictly decoupled from React components for deterministic unit testing.
 */

export const STATUS_CONFIG = {
  ok: {
    key: 'ok',
    label: 'Saudável',
    glyph: '✓',
    color: '#34D399',
    tint: '#10261E',
    sq: '#1F6F52',
    sqfg: '#D6FBEA',
    severity: 5,
  },
  running: {
    key: 'running',
    label: 'Produzindo',
    glyph: '•',
    color: '#6AA8FF',
    tint: '#112038',
    sq: '#2B5FB8',
    sqfg: '#E3EEFF',
    severity: 3,
  },
  attention: {
    key: 'attention',
    label: 'Atenção',
    glyph: '!',
    color: '#F5B546',
    tint: '#2A2010',
    sq: '#B47A12',
    sqfg: '#FFF1D6',
    severity: 2,
  },
  blocked: {
    key: 'blocked',
    label: 'Bloqueado',
    glyph: '×',
    color: '#FF8A7A',
    tint: '#2C1613',
    sq: '#B3402F',
    sqfg: '#FFE3DE',
    severity: 1,
  },
  paused: {
    key: 'paused',
    label: 'Pausado',
    glyph: '⏸',
    color: '#9099AA',
    tint: '#171B24',
    sq: '#2A3040',
    sqfg: '#C9CFDB',
    severity: 4,
  },
};

/**
 * Returns visual and textual metadata for a given status string.
 */
export function formatStatus(status) {
  const norm = String(status || '').toLowerCase();
  return (
    STATUS_CONFIG[norm] || {
      key: norm,
      label: status || 'Desconhecido',
      glyph: '?',
      color: '#9099AA',
      tint: '#171B24',
      sq: '#2A3040',
      sqfg: '#C9CFDB',
      severity: 99,
    }
  );
}

/**
 * Returns human-readable label and styling for video formats.
 * - quiz_dilemma → "Quiz · Escolhas difíceis"
 * - quiz_paper → "Quiz · Papel"
 * - traditional → "Tradicional"
 * - other → raw text
 */
export function formatVideoFormat(format) {
  if (!format) return { label: '—', color: '#9099AA' };
  const lower = String(format).toLowerCase().trim();

  if (lower === 'quiz_dilemma') {
    return { label: 'Quiz · Escolhas difíceis', color: '#7BE3D0' };
  }
  if (lower === 'quiz_paper') {
    return { label: 'Quiz · Papel', color: '#C7A9FF' };
  }
  if (lower === 'traditional') {
    return { label: 'Tradicional', color: '#8B9DFF' };
  }
  return { label: format, color: '#E8EBF1' };
}

/**
 * Formats relative time from an ISO timestamp string.
 * Returns "—" if null, undefined or invalid.
 */
export function formatRelativeTime(isoString, now = new Date()) {
  if (!isoString) return '—';
  const target = new Date(isoString);
  if (isNaN(target.getTime())) return '—';

  const diffMs = now.getTime() - target.getTime();
  if (diffMs < 0) return 'agora';

  const diffSec = Math.floor(diffMs / 1000);
  if (diffSec < 60) return 'agora';

  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `há ${diffMin} min`;

  const diffHours = Math.floor(diffMin / 60);
  if (diffHours < 24) return `há ${diffHours} h`;

  const diffDays = Math.floor(diffHours / 24);
  if (diffDays === 1) return 'há 1 dia';
  return `há ${diffDays} dias`;
}

/**
 * Formats a 24-hour approval rate (number between 0 and 1, or percentage).
 * Returns text and alert color. Returns "—" if null/undefined/NaN.
 */
export function formatApprovalRate(rate) {
  if (rate === null || rate === undefined || rate === '') {
    return { text: '—', color: '#9099AA', isNull: true };
  }
  const num = Number(rate);
  if (isNaN(num)) {
    return { text: '—', color: '#9099AA', isNull: true };
  }

  // If rate is given as a fraction 0..1 (e.g. 0.83), convert to percentage
  const pct = num <= 1.0 ? Math.round(num * 100) : Math.round(num);
  const color = pct < 80 ? '#FF8A7A' : '#E8EBF1';

  return {
    text: `${pct}%`,
    color,
    value: pct,
    isNull: false,
  };
}

/**
 * Formats channel ready_stock and target_stock safely, treating null/undefined as unknown ('—')
 * without masquerading errors as 0 or triggering low-stock warning colors.
 */
export function formatReadyStock(readyStock, targetStock = null) {
  const hasTarget = typeof targetStock === 'number' && !isNaN(targetStock) && targetStock > 0;
  const targetDisplay = hasTarget ? String(targetStock) : '—';

  if (readyStock === null || readyStock === undefined || typeof readyStock !== 'number' || isNaN(readyStock)) {
    return {
      isUnknown: true,
      readyDisplay: '—',
      targetDisplay,
      label: hasTarget ? `—/${targetDisplay}` : '—',
      pct: 0,
      barColor: '#6B7385',
    };
  }

  const pct = hasTarget ? Math.min(100, Math.round((readyStock / targetStock) * 100)) : 0;
  const barColor = readyStock <= 1 ? '#F5B546' : 'var(--fleet-accent)';

  return {
    isUnknown: false,
    readyDisplay: String(readyStock),
    targetDisplay,
    label: hasTarget ? `${readyStock}/${targetDisplay}` : String(readyStock),
    pct,
    barColor,
  };
}

/**
 * Formats fleet total_ready_stock safely (null/undefined -> '—').
 */
export function formatTotalReadyStock(totalReadyStock, isLoading = false) {
  if (isLoading || totalReadyStock === null || totalReadyStock === undefined || typeof totalReadyStock !== 'number' || isNaN(totalReadyStock)) {
    return {
      isUnknown: true,
      display: '—',
      barWidth: '0%',
    };
  }
  return {
    isUnknown: false,
    display: String(totalReadyStock),
    barWidth: totalReadyStock > 0 ? '100%' : '0%',
  };
}

/**
 * Sorts channels by severity (gravity) first, then alphabetically by name:
 * 1. blocked (severity 1)
 * 2. attention (severity 2)
 * 3. running (severity 3)
 * 4. paused (severity 4)
 * 5. ok (severity 5)
 */
export function sortChannelsBySeverity(channels) {
  if (!Array.isArray(channels)) return [];
  return [...channels].sort((a, b) => {
    const stA = formatStatus(a.status);
    const stB = formatStatus(b.status);
    if (stA.severity !== stB.severity) {
      return stA.severity - stB.severity;
    }
    const nameA = String(a.name || a.profile_id || '').toLowerCase();
    const nameB = String(b.name || b.profile_id || '').toLowerCase();
    return nameA.localeCompare(nameB);
  });
}

/**
 * Returns list of channels that need operator attention:
 * blocked first, then attention, then paused.
 */
export function getAttentionList(channels) {
  if (!Array.isArray(channels)) return [];
  const attentionPriorities = {
    blocked: 1,
    attention: 2,
  };

  return channels
    .filter((c) => {
      const s = String(c.status || '').toLowerCase();
      return s === 'blocked' || s === 'attention';
    })
    .sort((a, b) => {
      const pA = attentionPriorities[String(a.status || '').toLowerCase()] || 99;
      const pB = attentionPriorities[String(b.status || '').toLowerCase()] || 99;
      if (pA !== pB) return pA - pB;
      const nameA = String(a.name || a.profile_id || '').toLowerCase();
      const nameB = String(b.name || b.profile_id || '').toLowerCase();
      return nameA.localeCompare(nameB);
    });
}

/**
 * Filters a list of channels based on filter chip and text search query.
 */
export function filterChannels(channels, { filter = 'all', query = '' } = {}) {
  if (!Array.isArray(channels)) return [];
  const q = String(query || '').trim().toLowerCase();

  return channels.filter((channel) => {
    // 1. Text search on name, slug or niche
    if (q) {
      const name = String(channel.name || '').toLowerCase();
      const niche = String(channel.niche || '').toLowerCase();
      const slug = String(channel.slug || channel.profile_id || '').toLowerCase();
      if (!name.includes(q) && !niche.includes(q) && !slug.includes(q)) {
        return false;
      }
    }

    // 2. Filter chip
    const status = String(channel.status || '').toLowerCase();
    const format = String(channel.format || '').toLowerCase();

    if (filter === 'attention') {
      return status === 'attention' || status === 'blocked';
    }
    if (filter === 'quiz') {
      return format.includes('quiz');
    }
    if (filter === 'traditional') {
      return format === 'traditional';
    }
    if (filter === 'paused') {
      return status === 'paused';
    }
    if (filter !== 'all') {
      return status === filter;
    }
    return true;
  });
}
