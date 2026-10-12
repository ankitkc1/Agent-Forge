import { useState } from 'react';
import { ApiError, downloadArtifact, errorMessage } from '@/api/client';
import { ConfirmDialog, CopyButton, EmptyState, ErrorNotice, Notice, Skeleton } from '@/components/Feedback';
import { Icon, type IconName } from '@/components/Icon';
import { Link } from '@/components/Link';
import { StageRail } from '@/components/StageRail';
import { BuildStatusBadge } from '@/components/Status';
import { useBuildActions, useReport } from '@/hooks/queries';
import { useBuildLive, type LiveMode } from '@/hooks/useBuildLive';
import { useNow } from '@/hooks/useNow';
import { artifactFileName, formatDuration, humanize, relativeTime, shortHash, shortId } from '@/lib/format';
import { ActivityTab } from '@/pages/build/ActivityTab';
import { ArchitectureTab } from '@/pages/build/ArchitectureTab';
import { EvaluationTab } from '@/pages/build/EvaluationTab';
import { FilesTab } from '@/pages/build/FilesTab';
import { OverviewTab } from '@/pages/build/OverviewTab';
import { ProvenanceTab } from '@/pages/build/ProvenanceTab';
import { SecurityTab } from '@/pages/build/SecurityTab';
import { TestsTab } from '@/pages/build/TestsTab';
import { buildPath, navigate, type BuildTab } from '@/router';
import { TERMINAL_STATUSES, type Build, type BuildReport } from '@/types';

const TABS: Array<{ id: BuildTab; label: string; icon: IconName }> = [
  { id: 'overview', label: 'Overview', icon: 'chart' },
  { id: 'architecture', label: 'Architecture', icon: 'graph' },
  { id: 'tests', label: 'Tests', icon: 'beaker' },
  { id: 'evaluation', label: 'Evaluation', icon: 'target' },
  { id: 'security', label: 'Security', icon: 'shield' },
  { id: 'files', label: 'Files', icon: 'folder' },
  { id: 'provenance', label: 'Provenance', icon: 'seal' },
  { id: 'activity', label: 'Activity', icon: 'list' },
];

const LIVE_LABEL: Record<LiveMode, string> = {
  connecting: 'Connecting to live updates',
  live: 'Live',
  polling: 'Refreshing every few seconds',
  idle: '',
};

function tabCount(tab: BuildTab, report: Partial<BuildReport> | undefined): number | null {
  if (tab === 'tests') {
    const tests = report?.gates?.tests?.tests;
    return tests ? tests.failed + tests.errors || null : null;
  }
  if (tab === 'security') return report?.security?.findings.length || null;
  if (tab === 'evaluation') {
    const evaluation = report?.gates?.evaluation?.evaluation;
    return evaluation ? evaluation.cases - evaluation.passed_cases || null : null;
  }
  return null;
}

function Actions({ build }: { build: Build }) {
  const actions = useBuildActions(build.id);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const terminal = TERMINAL_STATUSES.has(build.status);
  const pending = actions.cancel.isPending || actions.retry.isPending || actions.remove.isPending;

  const download = async () => {
    setDownloadError(null);
    try {
      await downloadArtifact(build.id, artifactFileName(build.agent_name, build.id));
    } catch (error) {
      setDownloadError(errorMessage(error));
    }
  };

  return (
    <div className="head-actions">
      {!terminal ? (
        <button type="button" className="button button-quiet" disabled={pending || build.cancel_requested} onClick={() => actions.cancel.mutate()}>
          <Icon name="stop" />
          {build.cancel_requested ? 'Cancelling' : 'Cancel build'}
        </button>
      ) : null}
      {terminal ? (
        <button
          type="button"
          className="button button-quiet"
          disabled={pending}
          onClick={() => actions.retry.mutate(undefined, { onSuccess: next => navigate(buildPath(next.id)) })}
        >
          <Icon name="refresh" />
          Rebuild
        </button>
      ) : null}
      {terminal ? (
        <button type="button" className="button button-quiet button-danger-text" disabled={pending} onClick={() => setConfirmDelete(true)}>
          <Icon name="trash" />
          Delete
        </button>
      ) : null}
      {build.artifact_ready ? (
        <button type="button" className="button button-primary" onClick={() => void download()}>
          <Icon name="download" />
          Download source
        </button>
      ) : null}
      {[actions.cancel.error, actions.retry.error, actions.remove.error].filter(Boolean).map(error => (
        <ErrorNotice key={String(error)} error={error} title="The action failed" />
      ))}
      {downloadError ? <Notice tone="bad" title="Download failed">{downloadError}</Notice> : null}
      <ConfirmDialog
        open={confirmDelete}
        title="Delete this build?"
        confirmLabel="Delete build"
        pending={actions.remove.isPending}
        onClose={() => setConfirmDelete(false)}
        onConfirm={() => actions.remove.mutate(undefined, { onSuccess: () => navigate('/builds') })}
      >
        <p>The build record, its event log and the packaged repository are removed permanently. The specification stays available in your other builds.</p>
      </ConfirmDialog>
    </div>
  );
}

function FailureNotice({ build }: { build: Build }) {
  if (build.status !== 'failed' && build.status !== 'cancelled') return null;
  const stage = build.stages.find(item => item.status === 'failed' || item.status === 'cancelled');
  if (build.status === 'cancelled') {
    return <Notice tone="warn" title="Build cancelled">{stage ? `Stopped during ${stage.name.toLowerCase()}. Nothing was packaged.` : 'Nothing was packaged.'}</Notice>;
  }
  const evidenceTab: BuildTab | null = stage?.key === 'tests' ? 'tests' : stage?.key === 'evaluation' ? 'evaluation' : stage?.key === 'security' ? 'security' : stage?.key === 'quality' ? 'overview' : null;
  return (
    <Notice
      tone="bad"
      title={stage ? `${stage.name} failed` : 'Build failed'}
      action={
        evidenceTab ? (
          <Link className="button button-quiet" to={buildPath(build.id, evidenceTab)}>
            See evidence
          </Link>
        ) : undefined
      }
    >
      {build.error ?? 'A gate did not pass. Nothing was packaged.'}
    </Notice>
  );
}

export function BuildDetailPage({ id, tab, file }: { id: string; tab: BuildTab; file: string | null }) {
  const live = useBuildLive(id);
  const build = live.data;
  const running = build ? !TERMINAL_STATUSES.has(build.status) : false;
  const now = useNow(1000, running);
  const finished = build?.stages.filter(stage => stage.finished_at).length ?? 0;
  const report = useReport(id, `${build?.status ?? 'loading'}:${finished}`);

  if (live.isPending) {
    return (
      <div className="page">
        <Skeleton lines={6} />
      </div>
    );
  }
  if (live.error || !build) {
    const missing = live.error instanceof ApiError && live.error.status === 404;
    return (
      <div className="page">
        {missing ? (
          <EmptyState
            icon="builds"
            title="Build not found"
            action={
              <Link to="/builds" className="button button-quiet">
                All builds
              </Link>
            }
          >
            It may have been deleted or passed the retention period.
          </EmptyState>
        ) : (
          <ErrorNotice error={live.error} title="The build could not be loaded" onRetry={() => void live.refetch()} />
        )}
      </div>
    );
  }

  // The server computes duration when it serialises; while running, keep it ticking locally.
  const duration = running && build.started_at ? Math.max(0, (now - Date.parse(build.started_at)) / 1000) : build.duration_seconds;

  return (
    <div className="page build">
      <header className="build-head">
        <Link to="/builds" className="back">
          <Icon name="back" />
          Builds
        </Link>
        <div className="build-title">
          <div>
            <h1>{humanize(build.agent_name)}</h1>
            <div className="build-meta">
              <BuildStatusBadge status={build.status} />
              {running ? <span className={`live live-${live.mode}`}>{LIVE_LABEL[live.mode]}</span> : null}
              <span>
                Build <code>{shortId(build.id)}</code>
              </span>
              <span title={build.spec_hash}>
                Spec <code>{shortHash(build.spec_hash)}</code>
              </span>
              <span title={build.created_at}>Started {relativeTime(build.started_at ?? build.created_at, now)}</span>
              <span>{formatDuration(duration)}</span>
              {build.parent_build_id ? (
                <Link to={buildPath(build.parent_build_id)}>Rebuild of {shortId(build.parent_build_id)}</Link>
              ) : null}
            </div>
          </div>
          <Actions build={build} />
        </div>
        {running ? (
          <div className="progress" role="progressbar" aria-label="Build progress" aria-valuenow={Math.round(build.progress)} aria-valuemin={0} aria-valuemax={100}>
            <span style={{ width: `${build.progress}%` }} />
          </div>
        ) : null}
      </header>

      <FailureNotice build={build} />
      <StageRail stages={build.stages} now={now} />

      <nav className="tabs" aria-label="Build sections">
        {TABS.map(item => {
          const count = tabCount(item.id, report.data);
          return (
            <Link key={item.id} to={buildPath(build.id, item.id)} replace className={`tab ${tab === item.id ? 'is-active' : ''}`} aria-current={tab === item.id ? 'page' : undefined}>
              <Icon name={item.icon} />
              {item.label}
              {count ? <span className="tab-count">{count}</span> : null}
            </Link>
          );
        })}
        <CopyButton value={build.id} label="Copy build ID" className="button button-quiet tabs-copy" />
      </nav>

      <div className="tab-panel">
        {report.error && tab !== 'activity' && tab !== 'files' ? <ErrorNotice error={report.error} title="The build report could not be loaded" onRetry={() => void report.refetch()} /> : null}
        {tab === 'overview' ? <OverviewTab build={build} report={report.data} /> : null}
        {tab === 'architecture' ? <ArchitectureTab report={report.data} /> : null}
        {tab === 'tests' ? <TestsTab build={build} report={report.data} /> : null}
        {tab === 'evaluation' ? <EvaluationTab report={report.data} /> : null}
        {tab === 'security' ? <SecurityTab build={build} report={report.data} /> : null}
        {tab === 'files' ? <FilesTab build={build} selected={file} /> : null}
        {tab === 'provenance' ? <ProvenanceTab build={build} report={report.data} /> : null}
        {tab === 'activity' ? <ActivityTab build={build} live={running} /> : null}
      </div>
    </div>
  );
}
