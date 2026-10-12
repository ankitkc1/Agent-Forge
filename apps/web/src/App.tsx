import { useEffect, useState, type ReactNode } from 'react';
import { ApiError } from '@/api/client';
import { ApiKeyDialog } from '@/components/ApiKeyDialog';
import { Icon, type IconName } from '@/components/Icon';
import { Link } from '@/components/Link';
import { useSystem } from '@/hooks/queries';
import { BuildDetailPage } from '@/pages/BuildDetailPage';
import { BuildsPage } from '@/pages/BuildsPage';
import { ComposePage } from '@/pages/ComposePage';
import { NotFoundPage } from '@/pages/NotFoundPage';
import { SystemPage } from '@/pages/SystemPage';
import { TemplatesPage } from '@/pages/TemplatesPage';
import { useRoute, type Route } from '@/router';

const NAV: Array<{ to: string; label: string; icon: IconName; match: Route['name'][] }> = [
  { to: '/', label: 'New agent', icon: 'plus', match: ['compose'] },
  { to: '/builds', label: 'Builds', icon: 'builds', match: ['builds', 'build'] },
  { to: '/templates', label: 'Templates', icon: 'layers', match: ['templates'] },
  { to: '/system', label: 'System', icon: 'server', match: ['system'] },
];

const TITLES: Record<Route['name'], string> = {
  compose: 'New agent',
  builds: 'Builds',
  build: 'Build',
  templates: 'Templates',
  system: 'System',
  'not-found': 'Not found',
};

function Brand() {
  return (
    <Link to="/" className="brand" aria-label="AgentForge home">
      <svg viewBox="0 0 40 40" aria-hidden="true">
        <path d="M8 29.5 19.7 8 32 29.5h-6.8l-2.1-4.2h-7.2l3.3-6h.9l-1.8-3.8-7.5 14H8Z" fill="currentColor" />
        <path d="M21.7 29.5h10.5l-5.3-9.2-5.2 9.2Z" className="brand-accent" />
      </svg>
      <span>AgentForge</span>
    </Link>
  );
}

function ServerStatus({ onKey }: { onKey: () => void }) {
  const system = useSystem();
  const needsKey = system.error instanceof ApiError && system.error.unauthorized;
  if (needsKey) {
    return (
      <button type="button" className="server server-warn" onClick={onKey}>
        <Icon name="key" />
        <span className="server-text">
          <strong>API key required</strong>
          <small>Add a key to continue</small>
        </span>
      </button>
    );
  }
  if (system.isError) {
    return (
      <div className="server server-bad">
        <Icon name="alert" />
        <span className="server-text">
          <strong>API unreachable</strong>
          <small>Builds and compilation are unavailable</small>
        </span>
      </div>
    );
  }
  const info = system.data;
  return (
    <div className="server">
      <span className={`server-dot ${info ? 'is-up' : ''}`} aria-hidden="true" />
      <span className="server-text">
        <strong>{info ? `AgentForge ${info.version}` : 'Connecting…'}</strong>
        <small>{info ? `${info.sandbox.backend} sandbox, ${info.signing.enabled ? 'signed artifacts' : 'unsigned artifacts'}` : 'Checking the API'}</small>
      </span>
      {info && info.auth_mode === 'api_key' ? (
        <button type="button" className="icon-button" onClick={onKey} aria-label="Change API key">
          <Icon name="key" />
        </button>
      ) : null}
    </div>
  );
}

function Page({ route }: { route: Route }): ReactNode {
  switch (route.name) {
    case 'compose':
      return <ComposePage templateId={route.template} />;
    case 'builds':
      return <BuildsPage />;
    case 'build':
      return <BuildDetailPage id={route.id} tab={route.tab} file={route.file} />;
    case 'templates':
      return <TemplatesPage />;
    case 'system':
      return <SystemPage />;
    default:
      return <NotFoundPage path={route.path} />;
  }
}

export function App() {
  const route = useRoute();
  const [menuOpen, setMenuOpen] = useState(false);
  const [keyOpen, setKeyOpen] = useState(false);

  useEffect(() => {
    document.title = `${TITLES[route.name]} · AgentForge`;
  }, [route.name]);

  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <aside className={`sidebar ${menuOpen ? 'is-open' : ''}`} aria-label="Primary">
        <Brand />
        <nav className="nav">
          {NAV.map(item => {
            const active = item.match.includes(route.name);
            return (
              <Link key={item.to} to={item.to} className={`nav-link ${active ? 'is-active' : ''}`} aria-current={active ? 'page' : undefined} onClick={() => setMenuOpen(false)}>
                <Icon name={item.icon} />
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="sidebar-foot">
          <ServerStatus onKey={() => setKeyOpen(true)} />
          <a className="nav-link nav-quiet" href="/api/docs" target="_blank" rel="noreferrer">
            <Icon name="external" />
            API reference
          </a>
        </div>
      </aside>
      {menuOpen ? <button type="button" className="scrim" aria-label="Close navigation" onClick={() => setMenuOpen(false)} /> : null}
      <div className="frame">
        <header className="topbar">
          <button type="button" className="icon-button menu-button" aria-label="Open navigation" aria-expanded={menuOpen} onClick={() => setMenuOpen(open => !open)}>
            <Icon name="menu" />
          </button>
          <Brand />
        </header>
        <main id="main" className="main" tabIndex={-1}>
          <Page route={route} />
        </main>
      </div>
      <ApiKeyDialog open={keyOpen} onClose={() => setKeyOpen(false)} />
    </div>
  );
}
