import { CodeView } from '@/components/CodeView';
import { StateBadge } from '@/components/Status';
import { formatDuration } from '@/lib/format';
import type { CommandSummary, GateResult } from '@/types';

export function CommandOutput({ command }: { command: CommandSummary }) {
  return (
    <details className="command">
      <summary>
        <code>{command.command}</code>
        <span className={command.exit_code === 0 && !command.timed_out ? 'is-good' : 'is-bad'}>
          {command.timed_out ? 'timed out' : `exit ${command.exit_code}`}
        </span>
        <span>{formatDuration(command.duration_seconds)}</span>
      </summary>
      {command.output_tail ? <CodeView content={command.output_tail} label={`Output of ${command.command}`} /> : <p className="muted">No output.</p>}
    </details>
  );
}

export function GateCard({ title, gate, source }: { title: string; gate: GateResult | undefined; source: string }) {
  return (
    <section className="panel gate">
      <div className="gate-head">
        <h3>{title}</h3>
        {gate ? <StateBadge status={gate.status} /> : <span className="muted">Not run yet</span>}
      </div>
      {gate ? (
        <>
          <p>{gate.summary}</p>
          <p className="gate-meta">
            {formatDuration(gate.duration_seconds)}
            {gate.attempts > 1 ? `, ${gate.attempts} attempts` : ''}, evidence from {source}
          </p>
          {gate.commands.map((command, index) => (
            <CommandOutput key={`${command.command}-${index}`} command={command} />
          ))}
        </>
      ) : null}
    </section>
  );
}
