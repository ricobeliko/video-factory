import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  getReviewTasks,
  getReviewTaskVideoUrl,
  approveReviewTask,
  discardReviewTask,
} from '../../api';
import '../Fleet/fleet.css';
import './videoReview.css';

/**
 * VideoReviewView — Central de Revisão Visual de Vídeos (QG-V2.2 Complemento).
 * Permite ao operador humano assistir aos vídeos retidos pelo Quality Gate,
 * inspecionar os vereditos dos Gates e decidir visualmente entre:
 * - "Aprovar para estoque" (mesmo se score < 70, via override editorial seguro)
 * - "Descartar" (registrado permanentemente sem apagar MP4)
 */
function VideoReviewView({ onNavigate }) {
  const [filter, setFilter] = useState('pending'); // 'pending' | 'approved' | 'discarded'
  const [tasks, setTasks] = useState([]);
  const [counts, setCounts] = useState({ pending: 0, approved: 0, discarded: 0, total_inspected: 0 });
  const [selectedTaskId, setSelectedTaskId] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isActionInProgress, setIsActionInProgress] = useState(false);
  const [actionFeedback, setActionFeedback] = useState(null);
  const [errorMessage, setErrorMessage] = useState(null);
  const [editorialNote, setEditorialNote] = useState('');
  const [confirmDialog, setConfirmDialog] = useState(null); // { type: 'approve' | 'discard', task }
  const [showFullScript, setShowFullScript] = useState(false);
  const videoRef = useRef(null);

  const handleNavClick = (tab) => {
    if (onNavigate) {
      onNavigate(tab);
    }
  };

  // Carrega fila de revisão do backend
  const loadReviewQueue = useCallback(async (currentFilter = filter) => {
    setIsLoading(true);
    setErrorMessage(null);
    try {
      const res = await getReviewTasks(currentFilter);
      const data = res?.data || res;
      if (data) {
        const loadedTasks = data.tasks || [];
        setTasks(loadedTasks);
        if (data.counts) {
          setCounts(data.counts);
        }
        // Se a tarefa selecionada não estiver na lista ou for nula, seleciona a primeira
        setSelectedTaskId((prevId) => {
          if (!prevId || !loadedTasks.some((t) => t.task_id === prevId)) {
            return loadedTasks.length > 0 ? loadedTasks[0].task_id : null;
          }
          return prevId;
        });
      }
    } catch (err) {
      console.error('Falha ao carregar fila de revisão:', err);
      setErrorMessage(err.message || 'Falha na comunicação com a API de revisão.');
    } finally {
      setIsLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    loadReviewQueue(filter);
  }, [filter]);

  // Tarefa atualmente selecionada para o Player
  const selectedTask = useMemo(() => {
    if (!tasks || tasks.length === 0) return null;
    return tasks.find((t) => t.task_id === selectedTaskId) || tasks[0];
  }, [tasks, selectedTaskId]);

  // Ciclo de vida estável do player: vincula a nova URL diretamente sem dupla chamada de load()
  // e pausa a reprodução imediatamente ao trocar de tarefa.
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    if (selectedTask?.task_id) {
      const url = getReviewTaskVideoUrl(selectedTask.task_id);
      try {
        video.pause();
      } catch {
        // Ignora erro ao pausar
      }
      video.src = url;
      try {
        video.load(); // Chamada única determinística
      } catch {
        // Ignora erro de carregamento
      }
    } else {
      try {
        video.pause();
        video.removeAttribute('src');
        video.load();
      } catch {
        // Ignora erro de limpeza
      }
    }
  }, [selectedTask?.task_id]);

  // Cleanup de mídia exclusivamente no desmonte da Central de Revisão
  useEffect(() => {
    return () => {
      const video = videoRef.current;
      if (video) {
        try {
          video.pause();
          video.removeAttribute('src');
          video.load();
        } catch {
          // Ignora erro de desmonte
        }
      }
    };
  }, []);

  // Ação 1: Aprovação Manual para Estoque
  const handleConfirmApprove = async () => {
    if (!selectedTask) return;
    setIsActionInProgress(true);
    setErrorMessage(null);
    setActionFeedback(null);

    try {
      const res = await approveReviewTask(selectedTask.task_id, {
        operatorId: 'operator',
        note: editorialNote,
        confirm: 'APPROVE_FOR_STOCK',
      });
      const data = res?.data || res;
      setActionFeedback({
        type: 'success',
        message: data.message || `Vídeo "${selectedTask.topic}" aprovado com sucesso para o Ready Stock!`,
      });
      setConfirmDialog(null);
      setEditorialNote('');
      // Recarrega a fila
      await loadReviewQueue(filter);
      setTimeout(() => setActionFeedback(null), 5000);
    } catch (err) {
      console.error('Erro ao aprovar vídeo:', err);
      setErrorMessage(err.message || 'Falha ao aprovar o vídeo.');
      setConfirmDialog(null);
    } finally {
      setIsActionInProgress(false);
    }
  };

  // Ação 2: Descarte Editorial Definitivo
  const handleConfirmDiscard = async () => {
    if (!selectedTask) return;
    setIsActionInProgress(true);
    setErrorMessage(null);
    setActionFeedback(null);

    try {
      const res = await discardReviewTask(selectedTask.task_id, {
        operatorId: 'operator',
        note: editorialNote,
        confirm: 'DISCARD_HELD_VIDEO',
      });
      const data = res?.data || res;
      setActionFeedback({
        type: 'info',
        message: data.message || `Vídeo "${selectedTask.topic}" descartado da fila de revisão.`,
      });
      setConfirmDialog(null);
      setEditorialNote('');
      // Recarrega a fila
      await loadReviewQueue(filter);
      setTimeout(() => setActionFeedback(null), 5000);
    } catch (err) {
      console.error('Erro ao descartar vídeo:', err);
      setErrorMessage(err.message || 'Falha ao descartar o vídeo.');
      setConfirmDialog(null);
    } finally {
      setIsActionInProgress(false);
    }
  };

  return (
    <div className="fleet-root review-view">
      {/* 1. Header Global com Navegação Unificada */}
      <header className="fleet-header">
        <div className="fleet-brand">
          <div className="fleet-brand-logo" aria-hidden="true">
            <svg
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="#0A0C11"
              strokeWidth="2.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M5 4l14 8-14 8z" />
            </svg>
          </div>
          <span className="fleet-brand-title">Video Factory</span>
          <span className="fleet-mono fleet-brand-badge">V2</span>
        </div>

        <nav className="fleet-nav" aria-label="Navegação da Aplicação">
          <button
            type="button"
            className="fleet-nav-link"
            onClick={() => handleNavClick('frota')}
          >
            Frota
          </button>
          <button
            type="button"
            className="fleet-nav-link"
            onClick={() => handleNavClick('producao')}
          >
            Produção
          </button>
          <button
            type="button"
            className="fleet-nav-link"
            onClick={() => handleNavClick('diagnostico')}
          >
            Diagnóstico
          </button>
          <button type="button" className="fleet-nav-link" disabled title="Em breve">
            <span>Publicação</span>
            <span className="fleet-nav-soon">em breve</span>
          </button>
          <button type="button" className="fleet-nav-link active">
            Revisão
          </button>
          <button
            type="button"
            className="fleet-nav-link"
            onClick={() => handleNavClick('sistema')}
          >
            Sistema
          </button>
        </nav>

        <div className="fleet-header-right">
          <div className="fleet-sync-pill" title="Fila de revisão de qualidade">
            <span className="fleet-live-dot" aria-hidden="true" />
            <span className="fleet-sync-text">
              {isLoading ? 'carregando...' : `${tasks.length} ${tasks.length === 1 ? 'vídeo' : 'vídeos'}`}
            </span>
          </div>

          <button
            type="button"
            className="fleet-refresh-btn"
            onClick={() => loadReviewQueue(filter)}
            disabled={isLoading}
            title="Atualizar lista"
          >
            {isLoading ? '⏳' : '↻'}
          </button>
        </div>
      </header>

      {/* 2. Conteúdo Principal */}
      <main className="review-main">
        {/* Título da Tela e Barra de Filtros */}
        <div className="review-filter-bar">
          <div className="fleet-title-bar" style={{ marginBottom: 0 }}>
            <div>
              <h1 className="fleet-title">Central de Revisão de Vídeos</h1>
              <p className="fleet-subtitle">
                Inspeção visual e curadoria editorial humana de vídeos retidos pelo Quality Gate.
              </p>
            </div>
          </div>

          {/* Abas de Filtro */}
          <div className="review-filter-tabs" role="tablist" aria-label="Filtro de status de revisão">
            <button
              type="button"
              className={`review-tab-btn ${filter === 'pending' ? 'active--pending' : ''}`}
              onClick={() => setFilter('pending')}
              role="tab"
              aria-selected={filter === 'pending'}
            >
              <span>⏳ Pendentes</span>
              <span className="review-tab-count">{counts.pending}</span>
            </button>

            <button
              type="button"
              className={`review-tab-btn ${filter === 'approved' ? 'active--approved' : ''}`}
              onClick={() => setFilter('approved')}
              role="tab"
              aria-selected={filter === 'approved'}
            >
              <span>✅ Aprovados</span>
              <span className="review-tab-count">{counts.approved}</span>
            </button>

            <button
              type="button"
              className={`review-tab-btn ${filter === 'discarded' ? 'active--discarded' : ''}`}
              onClick={() => setFilter('discarded')}
              role="tab"
              aria-selected={filter === 'discarded'}
            >
              <span>🗑️ Descartados</span>
              <span className="review-tab-count">{counts.discarded}</span>
            </button>
          </div>
        </div>

        {/* Notificações de Feedback */}
        {actionFeedback && (
          <div className={`review-feedback review-feedback--${actionFeedback.type}`} role="status">
            <span>{actionFeedback.type === 'success' ? '✓' : 'ℹ️'}</span>
            <span>{actionFeedback.message}</span>
          </div>
        )}

        {errorMessage && (
          <div className="review-feedback review-feedback--error" role="alert">
            <span>⚠️</span>
            <span>{errorMessage}</span>
          </div>
        )}

        {/* Arena Principal de Inspeção */}
        {isLoading && tasks.length === 0 ? (
          <div className="review-empty-state">
            <div style={{ fontSize: '32px', marginBottom: '12px' }}>⏳</div>
            <p style={{ color: 'var(--fleet-muted)' }}>Carregando candidatos para revisão visual...</p>
          </div>
        ) : tasks.length === 0 ? (
          <div className="review-empty-state">
            <div style={{ fontSize: '48px', marginBottom: '16px' }}>✨</div>
            <h3 style={{ fontSize: '18px', fontWeight: 600, color: 'var(--fleet-title)', marginBottom: '6px' }}>
              Nenhum vídeo {filter === 'pending' ? 'pendente para revisão' : filter === 'approved' ? 'aprovado' : 'descartado'}
            </h3>
            <p style={{ fontSize: '14px', color: 'var(--fleet-muted)', maxWidth: '420px', margin: '0 auto' }}>
              {filter === 'pending'
                ? 'Todos os vídeos gerados com sucesso foram aproveitados no Ready Stock ou avaliados pelo operador.'
                : 'Nenhum registro encontrado nesta categoria.'}
            </p>
          </div>
        ) : selectedTask ? (
          <div className="review-arena">
            {/* Coluna 1: Player Vertical 9:16 */}
            <div className="review-player-card">
              <div className="review-player-header">
                <span className="review-player-title">Player Vertical (9:16)</span>
                <div className="review-player-badges">
                  <span className="review-player-badge">
                    {selectedTask.actual_duration ? `${Math.round(selectedTask.actual_duration)}s` : '—'}
                  </span>
                  <span className="review-player-badge">
                    {selectedTask.mp4_size_mb} MB
                  </span>
                </div>
              </div>

              <div className="review-video-canvas">
                <video
                  ref={videoRef}
                  controls
                  playsInline
                  preload="metadata"
                  className="review-video-element"
                >
                  Seu navegador não suporta a tag de vídeo HTML5.
                </video>
              </div>

              <div className="review-player-footer">
                Task ID: {selectedTask.task_id}
              </div>
            </div>

            {/* Coluna 2: Inspeção Editorial & Vereditos dos Gates */}
            <div className="review-details-col">
              {/* Card de Metadados e Título */}
              <div className="review-card">
                <div className="review-pill-row">
                  <span className="review-pill-niche">{selectedTask.niche || 'Nicho Geral'}</span>
                  <span className="review-pill-profile">{selectedTask.profile_id || 'default'}</span>
                  <span className="review-pill-platform">• Plataforma: YouTube Shorts</span>
                </div>

                <h2 className="review-topic-title">{selectedTask.topic}</h2>

                {selectedTask.hook_text && (
                  <div className="review-hook-box">
                    "{selectedTask.hook_text}"
                  </div>
                )}

                {/* Roteiro Narrativo Expandível */}
                {selectedTask.script_text && (
                  <div>
                    <button
                      type="button"
                      onClick={() => setShowFullScript(!showFullScript)}
                      className="review-script-toggle"
                    >
                      {showFullScript ? '▲ Ocultar Roteiro Narrativo' : '▼ Ver Roteiro Narrativo Completo'}
                    </button>

                    {showFullScript && (
                      <div className="review-script-box">
                        {selectedTask.script_text}
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* Card de Status dos Gates */}
              <div className="review-card">
                <h3 className="review-section-title">Status Canônico dos Gates</h3>

                <div className="review-gates-grid">
                  {/* 1. Quality Gate */}
                  <div className="review-gate-card">
                    <div className="review-gate-label">Quality Gate</div>
                    <div className="review-gate-score-row">
                      <span className={selectedTask.qg_v2_quality_score >= 70 ? 'review-gate-score-pass' : 'review-gate-score-warn'}>
                        {selectedTask.qg_v2_quality_score ? selectedTask.qg_v2_quality_score.toFixed(1) : '—'}
                      </span>
                      <span style={{ fontSize: '11px', fontWeight: 600, color: selectedTask.qg_v2_quality_score >= 70 ? 'var(--fleet-ok)' : 'var(--fleet-warning)' }}>
                        {selectedTask.qg_v2_quality_label}
                      </span>
                    </div>
                    <div className="review-gate-orig">
                      Orig: {selectedTask.original_quality_score?.toFixed(1)} ({selectedTask.original_quality_label})
                    </div>
                  </div>

                  {/* 2. Safety Gate */}
                  <div className="review-gate-card">
                    <div className="review-gate-label">Safety Gate</div>
                    <div className="review-gate-score-row">
                      <span className={selectedTask.safety_status === 'PASS' ? 'review-gate-score-pass' : 'review-gate-score-fail'}>
                        {selectedTask.safety_status === 'PASS' ? '✅ PASS' : '❌ BLOCK'}
                      </span>
                    </div>
                    <div className="review-gate-orig">Diretrizes de Conteúdo</div>
                  </div>

                  {/* 3. Copyright Gate */}
                  <div className="review-gate-card">
                    <div className="review-gate-label">Copyright Gate</div>
                    <div className="review-gate-score-row">
                      <span className={selectedTask.copyright_status === 'PASS' ? 'review-gate-score-pass' : 'review-gate-score-fail'}>
                        {selectedTask.copyright_status === 'PASS' ? '✅ PASS' : '❌ BLOCK'}
                      </span>
                    </div>
                    <div className="review-gate-orig">Proveniência & Licenças</div>
                  </div>
                </div>

                {/* Motivo da Decisão */}
                <div className="review-decision-reason">
                  <strong>Motivo da Decisão:</strong> {selectedTask.reason}
                </div>
              </div>

              {/* Card de Decisão Editorial */}
              <div className="review-card">
                <h3 className="review-section-title" style={{ color: 'var(--fleet-text)' }}>
                  Decisão Editorial do Operador
                </h3>

                {filter === 'pending' ? (
                  <>
                    <div className="review-input-group">
                      <label htmlFor="editorial-note-input" className="review-input-label">
                        Nota ou justificativa editorial (opcional):
                      </label>
                      <input
                        id="editorial-note-input"
                        type="text"
                        value={editorialNote}
                        onChange={(e) => setEditorialNote(e.target.value)}
                        placeholder="Ex: Roteiro com boa dinâmica visual, aprovado manualmente..."
                        className="review-text-input"
                      />
                    </div>

                    {confirmDialog ? (
                      <div className={`review-confirm-box review-confirm-box--${confirmDialog.type}`}>
                        <div style={{ fontWeight: 600, marginBottom: '8px', color: 'var(--fleet-text)' }}>
                          {confirmDialog.type === 'approve'
                            ? '⚠️ Confirmar aprovação editorial para o Ready Stock?'
                            : '⚠️ Confirmar descarte definitivo do vídeo?'}
                        </div>
                        <p style={{ fontSize: '13px', margin: '0 0 14px 0', color: 'var(--fleet-muted)' }}>
                          {confirmDialog.type === 'approve'
                            ? 'O vídeo entrará no estoque de publicação do canal como override humano.'
                            : 'O vídeo será excluído da esteira de publicação. O arquivo .mp4 permanecerá no disco.'}
                        </p>
                        <div style={{ display: 'flex', gap: '10px' }}>
                          <button
                            type="button"
                            className="review-btn-approve"
                            style={{
                              backgroundColor: confirmDialog.type === 'approve' ? 'var(--fleet-ok)' : 'var(--fleet-blocked)',
                            }}
                            onClick={confirmDialog.type === 'approve' ? handleConfirmApprove : handleConfirmDiscard}
                            disabled={isActionInProgress}
                          >
                            {isActionInProgress ? 'Processando...' : 'Sim, confirmar ação'}
                          </button>
                          <button
                            type="button"
                            className="review-tab-btn"
                            style={{ border: '1px solid var(--fleet-border)' }}
                            onClick={() => setConfirmDialog(null)}
                            disabled={isActionInProgress}
                          >
                            Cancelar
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div className="review-action-btns">
                        <button
                          type="button"
                          className="review-btn-approve"
                          onClick={() => setConfirmDialog({ type: 'approve', task: selectedTask })}
                          disabled={isActionInProgress}
                        >
                          <span>✅ Aprovar para Estoque</span>
                        </button>
                        <button
                          type="button"
                          className="review-btn-discard"
                          onClick={() => setConfirmDialog({ type: 'discard', task: selectedTask })}
                          disabled={isActionInProgress}
                        >
                          <span>🗑️ Descartar</span>
                        </button>
                      </div>
                    )}
                  </>
                ) : (
                  <div style={{ fontSize: '13px', color: 'var(--fleet-muted)' }}>
                    {filter === 'approved' ? (
                      <p style={{ margin: 0, color: 'var(--fleet-ok)' }}>
                        ✅ Este vídeo já foi aprovado e encontra-se disponível no Ready Stock.
                      </p>
                    ) : (
                      <p style={{ margin: 0, color: 'var(--fleet-blocked)' }}>
                        🗑️ Este vídeo foi descartado pelo operador e excluído da esteira de publicação.
                      </p>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        ) : null}

        {/* 3. Deck Inferior de Tarefas Candidatas */}
        {tasks.length > 1 && (
          <div className="review-deck-section">
            <h3 className="review-section-title">
              Outros Candidatos Nesta Fila ({tasks.length})
            </h3>

            <div className="review-deck-grid">
              {tasks.map((t) => {
                const isSelected = t.task_id === selectedTaskId;
                return (
                  <div
                    key={t.task_id}
                    onClick={() => {
                      setSelectedTaskId(t.task_id);
                      setConfirmDialog(null);
                    }}
                    className={`review-task-card ${isSelected ? 'is-selected' : ''}`}
                  >
                    <div className="review-card-top-row">
                      <span style={{ fontSize: '11px', color: 'var(--fleet-muted)', fontWeight: 600 }}>
                        {t.niche || 'Geral'}
                      </span>
                      <span
                        style={{
                          fontSize: '11px',
                          fontWeight: 700,
                          color: t.qg_v2_quality_score >= 70 ? 'var(--fleet-ok)' : 'var(--fleet-warning)',
                          backgroundColor: 'rgba(0,0,0,0.3)',
                          padding: '1px 6px',
                          borderRadius: '4px',
                          fontFamily: 'var(--fleet-mono)',
                        }}
                      >
                        {t.qg_v2_quality_score ? t.qg_v2_quality_score.toFixed(1) : '—'}
                      </span>
                    </div>

                    <div className="review-task-topic">
                      {t.topic}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

export default React.memo(VideoReviewView);
