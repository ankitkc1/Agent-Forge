import { Icon, type IconName } from '@/components/Icon';
import { formatDuration } from '@/lib/format';
import type { PipelineStage } from '@/types';

const ICON: Record<PipelineStage['status'], IconName> = {
  pending: 'clock',
  running: 'refresh',
  passed: 'check',
  failed: 'x',
  skipped: 'arrow',
  cancelled: 'stop',
};

function elapsed(stage: PipelineStage, now: number): number | null {
  if (!stage.started_at) return null;
  const end = stage.finished_at ? Date.parse(stage.finished_at) : now;
  return Math.max(0, (end - Date.parse(stage.started_at)) / 1000);
}

/** The ten pipeline stages in order; each stage carries the evidence summary the worker wrote. */
export function StageRail({ stages, now }: { stages: PipelineStage[]; now: number }) {
  return (
    <ol className="rail" aria-label="Pipeline stages">
      {stages.map((stage, index) => {
        const seconds = elapsed(stage, now);
        return (
          <li key={stage.key} className={`rail-stage is-${stage.status}`} aria-current={stage.status === 'running' ? 'step' : undefined}>
            <span className="rail-marker">
              <Icon name={ICON[stage.status]} className={stage.status === 'running' ? 'spin' : undefined} />
            </span>
            <div className="rail-text">
              <span className="rail-index">{index + 1}</span>
              <strong>{stage.name}</strong>
              <span className="rail-summary">{stage.summary ?? stage.status}</span>
              {seconds !== null || stage.attempts > 1 ? (
                <span className="rail-meta">
                  {seconds !== null ? formatDuration(seconds) : null}
                  {stage.attempts > 1 ? `${seconds !== null ? ', ' : ''}${stage.attempts} attempts` : null}
                </span>
              ) : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
