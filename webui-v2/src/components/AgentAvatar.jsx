import React from 'react';

/**
 * AgentAvatar — Tech-Factory Visual Identity for Autonomous Agents (R6A.6).
 * Features:
 * - Geometric cyber-orb with localized tonal gradient.
 * - Distinctive persona symbol / glyph.
 * - Categorical palette / accent glow.
 * - Subtle state-driven halo when RUNNING.
 * - 100% lightweight: CSS + inline SVG/emojis, zero external assets.
 */
export default function AgentAvatar({
  persona = {},
  accentColor = '#38bdf8',
  isRunning = false,
  size = 'md', // 'xs' (20px), 'sm' (26px), 'md' (34px), 'lg' (46px)
  className = '',
}) {
  const glyph = persona.avatar || '🤖';
  const code = persona.code || 'AGT';

  const sizeMap = {
    xs: { dim: 20, fontSize: 11, ringWidth: 1.5 },
    sm: { dim: 26, fontSize: 13, ringWidth: 1.5 },
    md: { dim: 34, fontSize: 16, ringWidth: 2 },
    lg: { dim: 46, fontSize: 22, ringWidth: 2.5 },
  };

  const { dim, fontSize, ringWidth } = sizeMap[size] || sizeMap.md;

  return (
    <div
      className={`agent-avatar-orb size-${size} ${isRunning ? 'is-running' : ''} ${className}`}
      style={{
        width: `${dim}px`,
        height: `${dim}px`,
        '--agent-accent': accentColor,
      }}
      title={`${persona.name || code} (${persona.role || 'Agente Operacional'})`}
      aria-label={`${persona.name || code}`}
    >
      {/* Outer ambient glow & orbital border */}
      <div
        className="avatar-orb-ring"
        style={{
          borderColor: accentColor,
          borderWidth: `${ringWidth}px`,
        }}
      />

      {/* Tonal inner surface with cyber-radial depth */}
      <div
        className="avatar-orb-surface"
        style={{
          background: `radial-gradient(circle at 35% 30%, ${accentColor}33 0%, rgba(15, 23, 42, 0.85) 75%, #0b0f19 100%)`,
        }}
      >
        <span
          className="avatar-orb-glyph"
          style={{ fontSize: `${fontSize}px` }}
          role="img"
          aria-hidden="true"
        >
          {glyph}
        </span>
      </div>

      {/* Active running energy aura */}
      {isRunning && (
        <div
          className="avatar-orb-pulse"
          style={{ borderColor: accentColor }}
        />
      )}
    </div>
  );
}
