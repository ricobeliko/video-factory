import React from 'react';

/**
 * FleetNav — Componente único de navegação entre as telas da Video Factory V2 (Fonte Única 3).
 * Compartilhado por: Frota, Produção, Diagnóstico, Publicação, Revisão e Sistema.
 * Preserva rótulos e ordem canônica das abas.
 */
export default function FleetNav({ activeTab, onNavigate }) {
  const handleNavClick = (tab) => {
    if (onNavigate) {
      onNavigate(tab);
    } else if (typeof window !== 'undefined') {
      window.location.hash = `#${tab}`;
    }
  };

  return (
    <nav className="fleet-nav" aria-label="Navegação da Aplicação">
      <button
        type="button"
        className={`fleet-nav-link ${activeTab === 'frota' ? 'active' : ''}`.trim()}
        onClick={() => handleNavClick('frota')}
      >
        Frota
      </button>
      <button
        type="button"
        className={`fleet-nav-link ${activeTab === 'producao' ? 'active' : ''}`.trim()}
        onClick={() => handleNavClick('producao')}
      >
        Produção
      </button>
      <button
        type="button"
        className={`fleet-nav-link ${activeTab === 'diagnostico' ? 'active' : ''}`.trim()}
        onClick={() => handleNavClick('diagnostico')}
      >
        Diagnóstico
      </button>
      <button
        type="button"
        className={`fleet-nav-link ${activeTab === 'publicacao' ? 'active' : ''}`.trim()}
        onClick={() => handleNavClick('publicacao')}
      >
        Publicação
      </button>
      <button
        type="button"
        className={`fleet-nav-link ${activeTab === 'video-review' ? 'active' : ''}`.trim()}
        onClick={() => handleNavClick('video-review')}
      >
        Revisão
      </button>
      <button
        type="button"
        className={`fleet-nav-link ${activeTab === 'sistema' ? 'active' : ''}`.trim()}
        onClick={() => handleNavClick('sistema')}
      >
        Sistema
      </button>
    </nav>
  );
}
