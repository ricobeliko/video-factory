import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  getReviewTasks,
  getReviewTaskVideoUrl,
  approveReviewTask,
  discardReviewTask,
} from '../../api';

/**
 * VideoReviewView — Central de Revisão Visual de Vídeos (QG-V2.2 Complemento).
 * Permite ao operador humano assistir aos vídeos retidos pelo Quality Gate,
 * inspecionar os vereditos dos Gates e decidir visualmente entre:
 * - "Aprovar para estoque" (mesmo se score < 70, via override editorial seguro)
 * - "Descartar" (registrado permanentemente sem apagar MP4)
 */
function VideoReviewView() {
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
    const video = videoRef.current;
    return () => {
      if (video) {
        try {
          video.pause();
          video.removeAttribute('src');
          video.load();
        } catch {
          // Ignora erro no desmonte
        }
      }
    };
  }, []);

  // Manipulador de Aprovação
  const handleApprove = async () => {
    if (!selectedTask || isActionInProgress) return;
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

  // Manipulador de Descarte
  const handleDiscard = async () => {
    if (!selectedTask || isActionInProgress) return;
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
    <div className="review-container" style={{ padding: '24px 32px', maxWidth: '1440px', margin: '0 auto', color: '#f8fafc' }}>
      {/* 1. Header & Navigation */}
      <div className="review-header-bar" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px', borderBottom: '1px solid rgba(255,255,255,0.08)', paddingBottom: '16px' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <span style={{ fontSize: '28px' }}>🎬</span>
            <h1 style={{ fontSize: '22px', fontWeight: 700, margin: 0, letterSpacing: '-0.02em', color: '#f8fafc' }}>
              Central de Revisão de Vídeos
            </h1>
            <span style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.05em', backgroundColor: 'rgba(56, 189, 248, 0.15)', color: '#38bdf8', padding: '3px 8px', borderRadius: '12px', fontWeight: 600, border: '1px solid rgba(56, 189, 248, 0.3)' }}>
              QG-V2.2
            </span>
          </div>
          <p style={{ margin: '4px 0 0 0', fontSize: '13px', color: '#94a3b8' }}>
            Inspeção visual e curadoria editorial humana de vídeos retidos pelo Quality Gate.
          </p>
        </div>

        {/* Filter Tabs */}
        <div className="review-filter-tabs" style={{ display: 'flex', gap: '8px', backgroundColor: 'rgba(15, 23, 42, 0.6)', padding: '4px', borderRadius: '10px', border: '1px solid rgba(255,255,255,0.08)' }}>
          <button
            type="button"
            className={`review-tab-btn ${filter === 'pending' ? 'active' : ''}`}
            onClick={() => setFilter('pending')}
            style={{
              padding: '8px 16px',
              borderRadius: '8px',
              border: 'none',
              backgroundColor: filter === 'pending' ? '#2563eb' : 'transparent',
              color: filter === 'pending' ? '#ffffff' : '#94a3b8',
              fontSize: '13px',
              fontWeight: 600,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              transition: 'all 0.15s ease',
            }}
          >
            <span>⏳ Pendentes</span>
            <span style={{ backgroundColor: filter === 'pending' ? 'rgba(255,255,255,0.25)' : 'rgba(255,255,255,0.1)', padding: '1px 6px', borderRadius: '10px', fontSize: '11px' }}>
              {counts.pending}
            </span>
          </button>

          <button
            type="button"
            className={`review-tab-btn ${filter === 'approved' ? 'active' : ''}`}
            onClick={() => setFilter('approved')}
            style={{
              padding: '8px 16px',
              borderRadius: '8px',
              border: 'none',
              backgroundColor: filter === 'approved' ? '#059669' : 'transparent',
              color: filter === 'approved' ? '#ffffff' : '#94a3b8',
              fontSize: '13px',
              fontWeight: 600,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              transition: 'all 0.15s ease',
            }}
          >
            <span>✅ Aprovados</span>
            <span style={{ backgroundColor: filter === 'approved' ? 'rgba(255,255,255,0.25)' : 'rgba(255,255,255,0.1)', padding: '1px 6px', borderRadius: '10px', fontSize: '11px' }}>
              {counts.approved}
            </span>
          </button>

          <button
            type="button"
            className={`review-tab-btn ${filter === 'discarded' ? 'active' : ''}`}
            onClick={() => setFilter('discarded')}
            style={{
              padding: '8px 16px',
              borderRadius: '8px',
              border: 'none',
              backgroundColor: filter === 'discarded' ? '#dc2626' : 'transparent',
              color: filter === 'discarded' ? '#ffffff' : '#94a3b8',
              fontSize: '13px',
              fontWeight: 600,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              transition: 'all 0.15s ease',
            }}
          >
            <span>🗑️ Descartados</span>
            <span style={{ backgroundColor: filter === 'discarded' ? 'rgba(255,255,255,0.25)' : 'rgba(255,255,255,0.1)', padding: '1px 6px', borderRadius: '10px', fontSize: '11px' }}>
              {counts.discarded}
            </span>
          </button>

          <button
            type="button"
            onClick={() => loadReviewQueue(filter)}
            disabled={isLoading}
            title="Atualizar lista"
            style={{
              padding: '8px 12px',
              borderRadius: '8px',
              border: '1px solid rgba(255,255,255,0.1)',
              backgroundColor: 'transparent',
              color: '#94a3b8',
              cursor: 'pointer',
              fontSize: '13px',
            }}
          >
            {isLoading ? '⏳' : '🔄'}
          </button>
        </div>
      </div>

      {/* Notifications / Feedback */}
      {actionFeedback && (
        <div
          style={{
            padding: '12px 16px',
            borderRadius: '8px',
            marginBottom: '16px',
            backgroundColor: actionFeedback.type === 'success' ? 'rgba(16, 185, 129, 0.15)' : 'rgba(56, 189, 248, 0.15)',
            border: `1px solid ${actionFeedback.type === 'success' ? '#10b981' : '#38bdf8'}`,
            color: actionFeedback.type === 'success' ? '#34d399' : '#38bdf8',
            fontSize: '14px',
            fontWeight: 500,
          }}
        >
          {actionFeedback.message}
        </div>
      )}

      {errorMessage && (
        <div
          style={{
            padding: '12px 16px',
            borderRadius: '8px',
            marginBottom: '16px',
            backgroundColor: 'rgba(239, 68, 68, 0.15)',
            border: '1px solid #ef4444',
            color: '#f87171',
            fontSize: '14px',
            fontWeight: 500,
          }}
        >
          ⚠️ {errorMessage}
        </div>
      )}

      {/* Main Review Arena */}
      {isLoading && tasks.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '60px 0', color: '#94a3b8' }}>
          <div style={{ fontSize: '32px', marginBottom: '12px' }}>⏳</div>
          <p>Carregando candidatos para revisão visual...</p>
        </div>
      ) : tasks.length === 0 ? (
        <div
          style={{
            textAlign: 'center',
            padding: '80px 20px',
            backgroundColor: 'rgba(15, 23, 42, 0.4)',
            borderRadius: '16px',
            border: '1px dashed rgba(255,255,255,0.1)',
          }}
        >
          <div style={{ fontSize: '48px', marginBottom: '16px' }}>✨</div>
          <h3 style={{ fontSize: '18px', fontWeight: 600, color: '#f8fafc', marginBottom: '6px' }}>
            Nenhum vídeo {filter === 'pending' ? 'pendente para revisão' : filter === 'approved' ? 'aprovado' : 'descartado'}
          </h3>
          <p style={{ fontSize: '14px', color: '#94a3b8', maxWidth: '420px', margin: '0 auto' }}>
            {filter === 'pending'
              ? 'Todos os vídeos gerados com sucesso foram aproveitados no Ready Stock ou avaliados pelo operador.'
              : 'Nenhum registro encontrado nesta categoria.'}
          </p>
        </div>
      ) : selectedTask ? (
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(320px, 420px) 1fr', gap: '28px', alignItems: 'start' }}>
          {/* Coluna 1: Vertical 9:16 Video Player */}
          <div
            className="video-player-card"
            style={{
              backgroundColor: '#090d16',
              borderRadius: '16px',
              border: '1px solid rgba(255,255,255,0.12)',
              overflow: 'hidden',
              boxShadow: '0 20px 40px rgba(0,0,0,0.6)',
            }}
          >
            <div style={{ padding: '12px 16px', borderBottom: '1px solid rgba(255,255,255,0.06)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: '12px', fontWeight: 600, color: '#94a3b8' }}>
                PLAYER VERTICAL (9:16)
              </span>
              <div style={{ display: 'flex', gap: '6px' }}>
                <span style={{ fontSize: '11px', padding: '2px 6px', borderRadius: '4px', backgroundColor: 'rgba(255,255,255,0.08)', color: '#cbd5e1' }}>
                  {selectedTask.actual_duration ? `${Math.round(selectedTask.actual_duration)}s` : '—'}
                </span>
                <span style={{ fontSize: '11px', padding: '2px 6px', borderRadius: '4px', backgroundColor: 'rgba(255,255,255,0.08)', color: '#cbd5e1' }}>
                  {selectedTask.mp4_size_mb} MB
                </span>
              </div>
            </div>

            {/* Video Canvas Container (9:16 aspect ratio) */}
            <div style={{ position: 'relative', width: '100%', aspectRatio: '9 / 16', backgroundColor: '#020617', display: 'flex', justifyContent: 'center', alignItems: 'center' }}>
              <video
                ref={videoRef}
                controls
                playsInline
                preload="metadata"
                style={{ width: '100%', height: '100%', objectFit: 'contain' }}
              >
                Seu navegador não suporta a tag de vídeo HTML5.
              </video>
            </div>

            <div style={{ padding: '12px 16px', backgroundColor: 'rgba(255,255,255,0.02)', fontSize: '11px', color: '#64748b', wordBreak: 'break-all' }}>
              Task ID: {selectedTask.task_id}
            </div>
          </div>

          {/* Coluna 2: Inspeção Editorial & Vereditos dos Gates */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
            {/* Card Principal de Metadados e Título */}
            <div
              style={{
                backgroundColor: 'rgba(15, 23, 42, 0.7)',
                borderRadius: '16px',
                border: '1px solid rgba(255,255,255,0.08)',
                padding: '24px',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
                <span style={{ fontSize: '12px', padding: '2px 8px', borderRadius: '12px', backgroundColor: 'rgba(168, 85, 247, 0.15)', color: '#c084fc', border: '1px solid rgba(168, 85, 247, 0.3)', fontWeight: 600 }}>
                  {selectedTask.niche || 'Nicho Geral'}
                </span>
                <span style={{ fontSize: '12px', padding: '2px 8px', borderRadius: '12px', backgroundColor: 'rgba(56, 189, 248, 0.15)', color: '#38bdf8', border: '1px solid rgba(56, 189, 248, 0.3)', fontWeight: 600 }}>
                  {selectedTask.profile_id || 'default'}
                </span>
                <span style={{ fontSize: '12px', color: '#64748b' }}>
                  • Plataforma: YouTube Shorts
                </span>
              </div>

              <h2 style={{ fontSize: '20px', fontWeight: 700, margin: '0 0 12px 0', color: '#f8fafc', lineHeight: 1.35 }}>
                {selectedTask.topic}
              </h2>

              {selectedTask.hook_text && (
                <div
                  style={{
                    backgroundColor: 'rgba(0,0,0,0.3)',
                    borderLeft: '3px solid #38bdf8',
                    padding: '10px 14px',
                    borderRadius: '0 8px 8px 0',
                    fontSize: '13px',
                    color: '#e2e8f0',
                    fontStyle: 'italic',
                    marginBottom: '16px',
                  }}
                >
                  "{selectedTask.hook_text}"
                </div>
              )}

              {/* Roteiro Expandível */}
              {selectedTask.script_text && (
                <div style={{ marginTop: '12px' }}>
                  <button
                    type="button"
                    onClick={() => setShowFullScript(!showFullScript)}
                    style={{
                      background: 'none',
                      border: 'none',
                      color: '#38bdf8',
                      fontSize: '12px',
                      cursor: 'pointer',
                      padding: 0,
                      fontWeight: 600,
                    }}
                  >
                    {showFullScript ? '▲ Ocultar Roteiro Narrativo' : '▼ Ver Roteiro Narrativo Completo'}
                  </button>

                  {showFullScript && (
                    <div
                      style={{
                        marginTop: '8px',
                        padding: '12px',
                        backgroundColor: 'rgba(0,0,0,0.4)',
                        borderRadius: '8px',
                        fontSize: '13px',
                        lineHeight: '1.6',
                        color: '#cbd5e1',
                        maxHeight: '220px',
                        overflowY: 'auto',
                        whiteSpace: 'pre-wrap',
                      }}
                    >
                      {selectedTask.script_text}
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Painel de Status dos 3 Gates */}
            <div
              style={{
                backgroundColor: 'rgba(15, 23, 42, 0.7)',
                borderRadius: '16px',
                border: '1px solid rgba(255,255,255,0.08)',
                padding: '20px 24px',
              }}
            >
              <h3 style={{ fontSize: '14px', fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em', margin: '0 0 16px 0' }}>
                Status Canônico dos Gates
              </h3>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '14px', marginBottom: '16px' }}>
                {/* 1. Quality Gate Card */}
                <div style={{ backgroundColor: 'rgba(0,0,0,0.3)', borderRadius: '10px', padding: '12px', border: '1px solid rgba(255,255,255,0.06)' }}>
                  <div style={{ fontSize: '11px', color: '#94a3b8', marginBottom: '6px' }}>Quality Gate</div>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: '6px' }}>
                    <span style={{ fontSize: '18px', fontWeight: 700, color: selectedTask.qg_v2_quality_score >= 70 ? '#34d399' : '#fbbf24' }}>
                      {selectedTask.qg_v2_quality_score ? selectedTask.qg_v2_quality_score.toFixed(1) : '—'}
                    </span>
                    <span style={{ fontSize: '11px', fontWeight: 600, color: selectedTask.qg_v2_quality_score >= 70 ? '#34d399' : '#fbbf24' }}>
                      {selectedTask.qg_v2_quality_label}
                    </span>
                  </div>
                  <div style={{ fontSize: '10px', color: '#64748b', marginTop: '4px' }}>
                    Orig: {selectedTask.original_quality_score?.toFixed(1)} ({selectedTask.original_quality_label})
                  </div>
                </div>

                {/* 2. Safety Gate Card */}
                <div style={{ backgroundColor: 'rgba(0,0,0,0.3)', borderRadius: '10px', padding: '12px', border: '1px solid rgba(255,255,255,0.06)' }}>
                  <div style={{ fontSize: '11px', color: '#94a3b8', marginBottom: '6px' }}>Safety Gate</div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <span style={{ fontSize: '14px', fontWeight: 700, color: selectedTask.safety_status === 'PASS' ? '#34d399' : '#f87171' }}>
                      {selectedTask.safety_status === 'PASS' ? '✅ PASS' : '❌ BLOCK'}
                    </span>
                  </div>
                  <div style={{ fontSize: '10px', color: '#64748b', marginTop: '4px' }}>
                    Diretrizes de Conteúdo
                  </div>
                </div>

                {/* 3. Copyright Gate Card */}
                <div style={{ backgroundColor: 'rgba(0,0,0,0.3)', borderRadius: '10px', padding: '12px', border: '1px solid rgba(255,255,255,0.06)' }}>
                  <div style={{ fontSize: '11px', color: '#94a3b8', marginBottom: '6px' }}>Copyright Gate</div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <span style={{ fontSize: '14px', fontWeight: 700, color: selectedTask.copyright_status === 'PASS' ? '#34d399' : '#f87171' }}>
                      {selectedTask.copyright_status === 'PASS' ? '✅ PASS' : '❌ BLOCK'}
                    </span>
                  </div>
                  <div style={{ fontSize: '10px', color: '#64748b', marginTop: '4px' }}>
                    Proveniência & Licenças
                  </div>
                </div>
              </div>

              {/* Banner de Motivo da Retenção */}
              <div
                style={{
                  backgroundColor: 'rgba(251, 191, 36, 0.08)',
                  border: '1px solid rgba(251, 191, 36, 0.25)',
                  padding: '10px 14px',
                  borderRadius: '8px',
                  fontSize: '12px',
                  color: '#fbbf24',
                  lineHeight: 1.5,
                }}
              >
                <strong>Motivo da Decisão:</strong> {selectedTask.reason}
              </div>
            </div>

            {/* Painel de Ação Editorial do Operador */}
            <div
              style={{
                backgroundColor: 'rgba(15, 23, 42, 0.7)',
                borderRadius: '16px',
                border: '1px solid rgba(255,255,255,0.08)',
                padding: '24px',
              }}
            >
              <h3 style={{ fontSize: '14px', fontWeight: 600, color: '#f8fafc', margin: '0 0 12px 0' }}>
                Decisão Editorial do Operador
              </h3>

              {filter === 'pending' ? (
                <>
                  <div style={{ marginBottom: '16px' }}>
                    <label style={{ display: 'block', fontSize: '12px', color: '#94a3b8', marginBottom: '6px' }}>
                      Nota ou justificativa editorial (opcional):
                    </label>
                    <input
                      type="text"
                      value={editorialNote}
                      onChange={(e) => setEditorialNote(e.target.value)}
                      placeholder="Ex: Roteiro com boa dinâmica visual, aprovado manualmente..."
                      style={{
                        width: '100%',
                        padding: '10px 14px',
                        backgroundColor: 'rgba(0,0,0,0.4)',
                        border: '1px solid rgba(255,255,255,0.12)',
                        borderRadius: '8px',
                        color: '#f8fafc',
                        fontSize: '13px',
                        outline: 'none',
                        boxSizing: 'border-box',
                      }}
                    />
                  </div>

                  {/* Confirmação Inline */}
                  {confirmDialog ? (
                    <div
                      style={{
                        padding: '16px',
                        backgroundColor: confirmDialog.type === 'approve' ? 'rgba(5, 150, 105, 0.2)' : 'rgba(220, 38, 38, 0.2)',
                        border: `1px solid ${confirmDialog.type === 'approve' ? '#059669' : '#dc2626'}`,
                        borderRadius: '10px',
                        marginBottom: '16px',
                      }}
                    >
                      <h4 style={{ margin: '0 0 8px 0', fontSize: '14px', color: '#f8fafc' }}>
                        {confirmDialog.type === 'approve'
                          ? 'Confirmar Aprovação para Ready Stock?'
                          : 'Confirmar Descarte Permanente da Fila?'}
                      </h4>
                      <p style={{ margin: '0 0 14px 0', fontSize: '12px', color: '#cbd5e1', lineHeight: 1.4 }}>
                        {confirmDialog.type === 'approve'
                          ? selectedTask.qg_v2_quality_score < 70
                            ? 'Este vídeo possui Quality Score abaixo de 70.0. Sua decisão aplicará um override editorial formal, preservando o score histórico e liberando o vídeo para o estoque autônomo sem publicação imediata.'
                            : 'Este vídeo possui Quality Score QG-V2 aprovado (>= 70.0). Ele será integrado imediatamente ao Ready Stock sem regeneração de cenas.'
                          : 'O vídeo será removido permanentemente da lista de pendentes e não reaparecerá após reinicializações. O arquivo MP4 e os registros históricos serão integralmente preservados.'}
                      </p>

                      <div style={{ display: 'flex', gap: '10px' }}>
                        <button
                          type="button"
                          onClick={confirmDialog.type === 'approve' ? handleApprove : handleDiscard}
                          disabled={isActionInProgress}
                          style={{
                            padding: '8px 18px',
                            backgroundColor: confirmDialog.type === 'approve' ? '#059669' : '#dc2626',
                            color: '#ffffff',
                            border: 'none',
                            borderRadius: '6px',
                            fontSize: '13px',
                            fontWeight: 600,
                            cursor: 'pointer',
                          }}
                        >
                          {isActionInProgress ? 'Processando...' : 'Confirmar e Aplicar'}
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirmDialog(null)}
                          disabled={isActionInProgress}
                          style={{
                            padding: '8px 14px',
                            backgroundColor: 'transparent',
                            color: '#94a3b8',
                            border: '1px solid rgba(255,255,255,0.15)',
                            borderRadius: '6px',
                            fontSize: '13px',
                            cursor: 'pointer',
                          }}
                        >
                          Cancelar
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div style={{ display: 'flex', gap: '12px' }}>
                      <button
                        type="button"
                        onClick={() => setConfirmDialog({ type: 'approve', task: selectedTask })}
                        disabled={isActionInProgress}
                        style={{
                          flex: 1,
                          padding: '12px 20px',
                          backgroundColor: '#059669',
                          color: '#ffffff',
                          border: 'none',
                          borderRadius: '8px',
                          fontSize: '14px',
                          fontWeight: 600,
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          gap: '8px',
                          transition: 'background-color 0.15s ease',
                        }}
                      >
                        <span>✅ Aprovar para Estoque</span>
                        {selectedTask.qg_v2_quality_score < 70 && (
                          <span style={{ fontSize: '10px', backgroundColor: 'rgba(0,0,0,0.3)', padding: '2px 6px', borderRadius: '4px' }}>
                            Override Humano
                          </span>
                        )}
                      </button>

                      <button
                        type="button"
                        onClick={() => setConfirmDialog({ type: 'discard', task: selectedTask })}
                        disabled={isActionInProgress}
                        style={{
                          padding: '12px 20px',
                          backgroundColor: 'transparent',
                          color: '#f87171',
                          border: '1px solid rgba(239, 68, 68, 0.4)',
                          borderRadius: '8px',
                          fontSize: '14px',
                          fontWeight: 600,
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '6px',
                          transition: 'all 0.15s ease',
                        }}
                      >
                        <span>🗑️ Descartar</span>
                      </button>
                    </div>
                  )}
                </>
              ) : (
                <div style={{ fontSize: '13px', color: '#94a3b8' }}>
                  {filter === 'approved' ? (
                    <p style={{ margin: 0, color: '#34d399' }}>
                      ✅ Este vídeo já foi aprovado e encontra-se disponível no Ready Stock.
                    </p>
                  ) : (
                    <p style={{ margin: 0, color: '#f87171' }}>
                      🗑️ Este vídeo foi descartado pelo operador e excluído da esteira de publicação.
                    </p>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      ) : null}

      {/* 3. Carrossel / Deck de Tarefas para Seleção */}
      {tasks.length > 1 && (
        <div style={{ marginTop: '36px', borderTop: '1px solid rgba(255,255,255,0.08)', paddingTop: '24px' }}>
          <h3 style={{ fontSize: '14px', fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '14px' }}>
            Outros Candidatos Nesta Fila ({tasks.length})
          </h3>

          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
              gap: '12px',
            }}
          >
            {tasks.map((t) => {
              const isSelected = t.task_id === selectedTaskId;
              return (
                <div
                  key={t.task_id}
                  onClick={() => {
                    setSelectedTaskId(t.task_id);
                    setConfirmDialog(null);
                  }}
                  style={{
                    backgroundColor: isSelected ? 'rgba(56, 189, 248, 0.12)' : 'rgba(15, 23, 42, 0.5)',
                    border: isSelected ? '1px solid #38bdf8' : '1px solid rgba(255,255,255,0.08)',
                    borderRadius: '10px',
                    padding: '12px',
                    cursor: 'pointer',
                    transition: 'all 0.15s ease',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                    <span style={{ fontSize: '11px', color: '#94a3b8', fontWeight: 600 }}>
                      {t.niche || 'Geral'}
                    </span>
                    <span
                      style={{
                        fontSize: '11px',
                        fontWeight: 700,
                        color: t.qg_v2_quality_score >= 70 ? '#34d399' : '#fbbf24',
                        backgroundColor: 'rgba(0,0,0,0.3)',
                        padding: '1px 6px',
                        borderRadius: '4px',
                      }}
                    >
                      {t.qg_v2_quality_score ? t.qg_v2_quality_score.toFixed(1) : '—'}
                    </span>
                  </div>

                  <div
                    style={{
                      fontSize: '13px',
                      fontWeight: 600,
                      color: isSelected ? '#f8fafc' : '#cbd5e1',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      display: '-webkit-box',
                      WebkitLineClamp: 2,
                      WebkitBoxOrient: 'vertical',
                      lineHeight: 1.35,
                    }}
                  >
                    {t.topic}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
export default React.memo(VideoReviewView);
