import { useState } from 'react';
import { downloadArtifact } from '@/api/client';
import { EmptyState, ErrorNotice, Skeleton } from '@/components/Feedback';
import { Icon } from '@/components/Icon';
import { Link } from '@/components/Link';
import { BuildStatusBadge } from '@/components/Status';
import { useBuildList } from '@/hooks/queries';
import { useDebouncedValue } from '@/hooks/useDebouncedValue';
import { useNow } from '@/hooks/useNow';
import { artifactFileName, formatDuration, formatPercent, humanize, relativeTime, repositoryName, shortId } from '@/lib/format';
import { buildPath } from '@/router';
import type { BuildStatus, BuildSummary } from '@/types';

const FILTERS: Array<{ value: BuildStatus | undefined; label: string }> = [
  { value: undefined, label: 'All' },
  { value: 'running', label: 'Running' },
  { value: 'succeeded', label: 'Verified' },
  { value: 'failed', label: 'Failed' },
  { value: 'cancelled', label: 'Cancelled' },
];

function Evidence({ build }: { build: BuildSummary }) {
  const metrics = build.metrics;
  if (!metrics) {
    return <span className="muted">{build.status === 'failed' ? (build.error ?? 'Failed before evidence was collected') : (build.current_stage ?? 'Waiting for a worker')}</span>;
  }
  return (
    <span className="evidence">
      <span title="Tests passed / total">
        {metrics.tests_passed}/{metrics.tests_total} tests
      </span>
      <span title="Offline task success">{formatPercent(metrics.task_success)} task success</span>
      <span title="Unsafe actions in adversarial evaluation" className={metrics.unsafe_actions ? 'is-bad' : ''}>
        {metrics.unsafe_actions} unsafe
      </span>
    </span>
  );
}

export function BuildsPage() {
  const [status, setStatus] = useState<BuildStatus | undefined>(undefined);
  const [search, setSearch] = useState('');
  const agent = useDebouncedValue(search.trim(), 300);
  const builds = useBuildList({ status, agent: agent || undefined });
  const now = useNow(30_000);
  const rows = builds.data?.pages.flatMap(page => page.items) ?? [];

  return (
    <div className="page">
      <header className="page-head page-head-row">
        <div>
          <h1>Builds</h1>
          <p>Every build runs the generated repository's own lint, tests and evaluations in the sandbox before it can be downloaded.</p>
        </div>
        <Link to="/" className="button button-primary">
          <Icon name="plus" />
          New agent
        </Link>
      </header>

      <div className="toolbar">
        <div className="segmented" role="group" aria-label="Filter by status">
          {FILTERS.map(filter => (
            <button key={filter.label} type="button" className={status === filter.value ? 'is-selected' : ''} aria-pressed={status === filter.value} onClick={() => setStatus(filter.value)}>
              {filter.label}
            </button>
          ))}
        </div>
        <label className="search">
          <Icon name="search" />
          <span className="sr-only">Filter by agent name</span>
          <input type="search" placeholder="Agent name" value={search} onChange={event => setSearch(event.target.value)} />
        </label>
      </div>

      {builds.error ? <ErrorNotice error={builds.error} title="Builds could not be loaded" onRetry={() => void builds.refetch()} /> : null}
      {builds.isPending ? (
        <div className="panel">
          <Skeleton lines={5} />
        </div>
      ) : rows.length === 0 && !builds.error ? (
        <EmptyState
          icon="builds"
          title={status || agent ? 'No builds match these filters' : 'No builds yet'}
          action={
            status || agent ? (
              <button
                type="button"
                className="button button-quiet"
                onClick={() => {
                  setStatus(undefined);
                  setSearch('');
                }}
              >
                Clear filters
              </button>
            ) : (
              <Link to="/" className="button button-primary">
                Compile a requirement
              </Link>
            )
          }
        >
          {status || agent ? 'Try another status or name.' : 'Describe an agent and AgentForge will generate, test and sign its repository.'}
        </EmptyState>
      ) : (
        <div className="panel table-panel">
          <table className="table builds-table">
            <thead>
              <tr>
                <th scope="col">Agent</th>
                <th scope="col">Status</th>
                <th scope="col">Evidence</th>
                <th scope="col">Started</th>
                <th scope="col">Duration</th>
                <th scope="col">
                  <span className="sr-only">Download</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map(build => (
                <tr key={build.id}>
                  <td>
                    <Link to={buildPath(build.id)} className="row-link">
                      <strong>{humanize(build.agent_name)}</strong>
                      <code>{shortId(build.id)}</code>
                    </Link>
                  </td>
                  <td>
                    <BuildStatusBadge status={build.status} />
                    {build.status === 'running' ? <span className="progress-inline">{Math.round(build.progress)}%</span> : null}
                  </td>
                  <td>
                    <Evidence build={build} />
                  </td>
                  <td title={build.created_at}>{relativeTime(build.created_at, now)}</td>
                  <td>{formatDuration(build.duration_seconds)}</td>
                  <td className="cell-action">
                    {build.artifact_ready ? (
                      <button
                        type="button"
                        className="icon-button"
                        aria-label={`Download ${repositoryName(build.agent_name)} source`}
                        title="Download source"
                        onClick={() => void downloadArtifact(build.id, artifactFileName(build.agent_name, build.id))}
                      >
                        <Icon name="download" />
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {builds.hasNextPage ? (
            <div className="table-foot">
              <button type="button" className="button button-quiet" onClick={() => void builds.fetchNextPage()} disabled={builds.isFetchingNextPage}>
                {builds.isFetchingNextPage ? 'Loading' : 'Load older builds'}
              </button>
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}
