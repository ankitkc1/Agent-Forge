import { Icon, type IconName } from '@/components/Icon';
import type { BuildStatus, GateStatus, Severity, StageStatus } from '@/types';

type Tone = 'neutral' | 'active' | 'good' | 'bad' | 'warn' | 'muted' | 'review';

const BUILD: Record<BuildStatus, { label: string; tone: Tone; icon: IconName }> = {
  queued: { label: 'Queued', tone: 'neutral', icon: 'clock' },
  running: { label: 'Running', tone: 'active', icon: 'refresh' },
  succeeded: { label: 'Verified', tone: 'good', icon: 'check' },
  failed: { label: 'Failed', tone: 'bad', icon: 'x' },
  cancelled: { label: 'Cancelled', tone: 'muted', icon: 'stop' },
};

const STAGE: Record<StageStatus | GateStatus, { label: string; tone: Tone }> = {
  pending: { label: 'Pending', tone: 'neutral' },
  running: { label: 'Running', tone: 'active' },
  passed: { label: 'Passed', tone: 'good' },
  failed: { label: 'Failed', tone: 'bad' },
  error: { label: 'Error', tone: 'bad' },
  warning: { label: 'Warning', tone: 'warn' },
  skipped: { label: 'Skipped', tone: 'muted' },
  cancelled: { label: 'Cancelled', tone: 'muted' },
};

const SEVERITY: Record<Severity, Tone> = { critical: 'bad', high: 'bad', medium: 'warn', low: 'neutral', info: 'muted' };

export function BuildStatusBadge({ status }: { status: BuildStatus }) {
  const meta = BUILD[status];
  return (
    <span className={`badge tone-${meta.tone}`}>
      <Icon name={meta.icon} className={status === 'running' ? 'spin' : undefined} />
      {meta.label}
    </span>
  );
}

export function StateBadge({ status }: { status: StageStatus | GateStatus }) {
  const meta = STAGE[status];
  return <span className={`badge tone-${meta.tone}`}>{meta.label}</span>;
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  return <span className={`badge tone-${SEVERITY[severity]} severity`}>{severity}</span>;
}

export function ModeBadge({ mode, approval }: { mode: 'read' | 'draft' | 'execute'; approval?: boolean }) {
  return (
    <span className={`mode mode-${mode}`} title={approval ? 'Requires human approval' : undefined}>
      {mode}
      {approval ? <Icon name="lock" /> : null}
    </span>
  );
}
