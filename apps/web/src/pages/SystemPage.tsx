import { api } from '@/api/client';
import { ErrorNotice, Skeleton } from '@/components/Feedback';
import { Icon } from '@/components/Icon';
import { useSystem } from '@/hooks/queries';
import { formatDuration, humanize } from '@/lib/format';

const AUTH: Record<string, string> = {
  none: 'None (development only)',
  api_key: 'API keys',
  trusted_header: 'Identity from the authenticating proxy',
};

export function SystemPage() {
  const system = useSystem();
  if (system.isPending) {
    return (
      <div className="page">
        <Skeleton lines={6} />
      </div>
    );
  }
  if (system.error || !system.data) {
    return (
      <div className="page">
        <ErrorNotice error={system.error} title="System information is unavailable" onRetry={() => void system.refetch()} />
      </div>
    );
  }
  const info = system.data;
  return (
    <div className="page">
      <header className="page-head">
        <h1>System</h1>
        <p>How this AgentForge instance compiles, executes and signs builds.</p>
      </header>
      <div className="system-grid">
        <section className="panel">
          <h2>Instance</h2>
          <dl className="facts facts-wide">
            <div>
              <dt>Version</dt>
              <dd>{info.version}</dd>
            </div>
            <div>
              <dt>Environment</dt>
              <dd>{humanize(info.environment)}</dd>
            </div>
            <div>
              <dt>Authentication</dt>
              <dd>{AUTH[info.auth_mode] ?? info.auth_mode}</dd>
            </div>
          </dl>
        </section>
        <section className="panel">
          <h2>Compiler</h2>
          <dl className="facts facts-wide">
            <div>
              <dt>Engines</dt>
              <dd>{info.compiler.engines.map(engine => (engine === 'llm' ? `model-assisted (${info.compiler.llm_provider})` : 'deterministic')).join(', ')}</dd>
            </div>
            <div>
              <dt>Domain packs</dt>
              <dd>{info.compiler.domains.map(humanize).join(', ')}</dd>
            </div>
            <div>
              <dt>Workflow steps</dt>
              <dd>{info.step_kinds.map(kind => kind.replaceAll('_', ' ')).join(', ')}</dd>
            </div>
          </dl>
        </section>
        <section className="panel">
          <h2>Execution</h2>
          <dl className="facts facts-wide">
            <div>
              <dt>Sandbox</dt>
              <dd>{info.sandbox.backend === 'docker' ? 'Docker, one locked-down container per command' : 'Isolated process with resource limits'}</dd>
            </div>
            <div>
              <dt>Workers</dt>
              <dd>{info.dispatch === 'inline' ? 'Builds run inside the API process (development mode)' : 'Celery workers on the build queue'}</dd>
            </div>
            <div>
              <dt>Command timeout</dt>
              <dd>{formatDuration(info.sandbox.timeout_seconds)}</dd>
            </div>
            <div>
              <dt>Repair</dt>
              <dd>
                Up to {info.repair.max_attempts} attempts{info.repair.llm ? ', model-assisted patches enabled' : ', mechanical fixes only'}
              </dd>
            </div>
            <div>
              <dt>Concurrency</dt>
              <dd>{info.limits.max_active_builds} active builds</dd>
            </div>
            <div>
              <dt>Retention</dt>
              <dd>{info.limits.build_retention_days} days</dd>
            </div>
          </dl>
        </section>
        <section className="panel">
          <h2>Signing</h2>
          {info.signing.enabled ? (
            <>
              <p>
                Artifacts are signed with Ed25519 key <code>{info.signing.key_id}</code>. Share the public key with anyone who installs generated agents.
              </p>
              <a className="button button-quiet" href={api.signingKeyUrl()} download="agentforge-signing-key.pub">
                <Icon name="download" />
                Public key
              </a>
            </>
          ) : (
            <p>
              No signing key is configured, so artifacts carry a checksum manifest but no signature. Generate one with <code>agentforge generate-signing-key</code> and set{' '}
              <code>AGENTFORGE_SIGNING_KEY</code>.
            </p>
          )}
        </section>
      </div>
    </div>
  );
}
