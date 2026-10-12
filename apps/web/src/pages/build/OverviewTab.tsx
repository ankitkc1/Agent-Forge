import { useState } from 'react';
import { downloadArtifact, errorMessage } from '@/api/client';
import { Notice } from '@/components/Feedback';
import { Icon } from '@/components/Icon';
import { CountTile, TargetMeter } from '@/components/Meter';
import { artifactFileName, formatBytes, formatDuration, formatInteger, repositoryName, shortHash } from '@/lib/format';
import { GateCard } from '@/pages/build/GateDetails';
import type { Build, BuildReport } from '@/types';

const REPOSITORY_LAYOUT = [
  'src/agent/  graph.py, state.py, prompts.py, nodes.py',
  'src/tools/  typed, allowlisted tool modules',
  'src/rag/  ingestion, embeddings, retrieval with citations',
  'src/memory/  conversation memory and checkpoints',
  'src/api/  FastAPI service with approval endpoints',
  'mcp/  Model Context Protocol server',
  'tests/  unit, integration and agent suites',
  'evals/  dataset.json and graders.py',
  'Dockerfile, docker-compose.yml, pyproject.toml, .env.example',
  'agent-spec.yaml, architecture.md, README.md',
];

function Delivery({ build, report }: { build: Build; report: Partial<BuildReport> | undefined }) {
  const [error, setError] = useState<string | null>(null);
  const name = repositoryName(build.agent_name);
  const signature = report?.package?.signature;
  const download = async () => {
    setError(null);
    try {
      await downloadArtifact(build.id, artifactFileName(build.agent_name, build.id));
    } catch (failure) {
      setError(errorMessage(failure));
    }
  };
  return (
    <section className="delivery">
      <div className="delivery-copy">
        <h2>
          <code>{name}/</code> is ready
        </h2>
        <p>
          Generated from specification <code>{shortHash(build.spec_hash)}</code>, passed its own lint, tests and evaluation suite in the sandbox, and was
          security-checked{signature?.signed ? ' and signed' : ''} before packaging.
        </p>
        <ul className="layout-list">
          {REPOSITORY_LAYOUT.map(line => (
            <li key={line}>
              <code>{line.split('  ')[0]}</code>
              {line.includes('  ') ? <span>{line.split('  ')[1]}</span> : null}
            </li>
          ))}
        </ul>
      </div>
      <div className="delivery-action">
        <button type="button" className="button button-primary button-large" onClick={() => void download()}>
          <Icon name="download" />
          Download source
        </button>
        <dl className="facts">
          <div>
            <dt>Archive</dt>
            <dd>
              {formatBytes(build.artifact_size)}, {formatInteger(report?.package?.files)} files
            </dd>
          </div>
          <div>
            <dt>SHA-256</dt>
            <dd>
              <code title={build.artifact_sha256 ?? undefined}>{shortHash(build.artifact_sha256, 16)}</code>
            </dd>
          </div>
          <div>
            <dt>Signature</dt>
            <dd>{signature?.signed ? <code>{signature.key_id}</code> : 'Unsigned'}</dd>
          </div>
        </dl>
        {error ? <Notice tone="bad" title="Download failed">{error}</Notice> : null}
      </div>
    </section>
  );
}

function Timings({ build, report }: { build: Build; report: Partial<BuildReport> | undefined }) {
  const timings = report?.timings ?? {};
  const rows = build.stages.filter(stage => timings[stage.key] !== undefined).map(stage => ({ name: stage.name, seconds: timings[stage.key]! }));
  if (!rows.length) return null;
  const max = Math.max(...rows.map(row => row.seconds), 0.001);
  return (
    <section className="panel">
      <h3>Where the time went</h3>
      <ul className="bars" aria-label="Stage durations">
        {rows.map(row => (
          <li key={row.name}>
            <span>{row.name}</span>
            <span className="bar">
              <span style={{ width: `${Math.max(1, (row.seconds / max) * 100)}%` }} />
            </span>
            <span className="bar-value">{formatDuration(row.seconds)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function OverviewTab({ build, report }: { build: Build; report: Partial<BuildReport> | undefined }) {
  const metrics = build.metrics;
  const evaluation = report?.gates?.evaluation?.evaluation;
  const thresholds = evaluation?.thresholds ?? {};
  const notes = [...(report?.generation?.notes ?? []), ...(report?.notes ?? [])];

  return (
    <div className="stack">
      {build.artifact_ready ? <Delivery build={build} report={report} /> : null}
      {!metrics && build.status === 'running' ? (
        <Notice title="Evidence arrives as each gate finishes">
          Tests, coverage and evaluation results are parsed from the reports the generated repository writes in the sandbox.
        </Notice>
      ) : null}

      {metrics ? (
        <section className="measures" aria-label="Quality evidence">
          <TargetMeter label="Task success" value={metrics.task_success} target={thresholds.task_success ?? null} source="eval-report.json" />
          <TargetMeter label="Tool accuracy" value={metrics.tool_accuracy} target={thresholds.tool_accuracy ?? null} source="eval-report.json" />
          <TargetMeter label="Line coverage" value={metrics.test_coverage} target={null} source="coverage.json" />
          <div className="tiles">
            <CountTile
              label="Tests"
              value={`${formatInteger(metrics.tests_passed)}/${formatInteger(metrics.tests_total)}`}
              detail={metrics.tests_failed ? `${metrics.tests_failed} failing` : 'passed in the sandbox'}
              tone={metrics.tests_failed ? 'bad' : 'good'}
            />
            <CountTile
              label="Unsafe actions"
              value={formatInteger(metrics.unsafe_actions)}
              detail={`across ${formatInteger(metrics.adversarial_cases)} adversarial cases`}
              tone={metrics.unsafe_actions ? 'bad' : 'good'}
            />
            <CountTile label="Security findings" value={formatInteger(metrics.security_findings)} detail="static analysis and policy" tone={metrics.security_findings ? 'warn' : 'good'} />
            <CountTile label="Repairs" value={formatInteger(metrics.repair_attempts)} detail={metrics.repair_attempts ? 'automatic fixes applied' : 'none needed'} />
          </div>
        </section>
      ) : null}

      <div className="gate-grid">
        <GateCard title="Static checks" gate={report?.gates?.quality} source="ruff and the Python compiler" />
        <GateCard title="Sandbox tests" gate={report?.gates?.tests} source="junit.xml and coverage.json" />
        <GateCard title="Evaluation suite" gate={report?.gates?.evaluation} source="eval-report.json" />
      </div>

      {report?.repairs?.length ? (
        <section className="panel">
          <h3>Repair attempts</h3>
          <ol className="repairs">
            {report.repairs.map(repair => (
              <li key={repair.number}>
                <strong>
                  Attempt {repair.number}: {repair.strategy}
                </strong>
                <span className={`repair-outcome is-${repair.outcome}`}>{repair.outcome}</span>
                <p>
                  {repair.gate} gate{repair.changed_files.length ? `, changed ${repair.changed_files.join(', ')}` : ''}
                </p>
                {repair.detail ? <pre className="detail">{repair.detail}</pre> : null}
              </li>
            ))}
          </ol>
        </section>
      ) : null}

      <div className="split">
        <Timings build={build} report={report} />
        {notes.length ? (
          <section className="panel">
            <h3>Notes from the generator</h3>
            <ul className="notes">
              {notes.map(note => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </section>
        ) : null}
      </div>
    </div>
  );
}
