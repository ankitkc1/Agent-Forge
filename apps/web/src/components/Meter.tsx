import { formatPercent } from '@/lib/format';

/**
 * A measured ratio against its target. The target tick makes "how far above the bar" readable at a
 * glance; the label always states both numbers so color is never the only signal.
 */
export function TargetMeter({ label, value, target, source }: { label: string; value: number | null; target: number | null; source: string }) {
  const met = value !== null && target !== null ? value >= target : null;
  return (
    <div className={`measure ${met === false ? 'is-missed' : met ? 'is-met' : ''}`}>
      <div className="measure-head">
        <span>{label}</span>
        <strong>{formatPercent(value)}</strong>
      </div>
      <div className="measure-track" role="img" aria-label={`${label} ${formatPercent(value)}${target !== null ? `, target ${formatPercent(target)}` : ''}`}>
        <span className="measure-fill" style={{ width: `${Math.min(100, Math.max(0, (value ?? 0) * 100))}%` }} />
        {target !== null ? <span className="measure-target" style={{ left: `${Math.min(100, target * 100)}%` }} /> : null}
      </div>
      <div className="measure-foot">
        <span>{target !== null ? `Target ${formatPercent(target)}` : 'No target set'}</span>
        <span>{source}</span>
      </div>
    </div>
  );
}

export function CountTile({ label, value, detail, tone }: { label: string; value: string; detail: string; tone?: 'good' | 'bad' | 'warn' }) {
  return (
    <div className={`tile ${tone ? `tile-${tone}` : ''}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}
