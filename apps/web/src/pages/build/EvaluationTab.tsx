import { useMemo, useState } from 'react';
import { EmptyState } from '@/components/Feedback';
import { Icon } from '@/components/Icon';
import { TargetMeter } from '@/components/Meter';
import { formatPercent, humanize } from '@/lib/format';
import type { BuildReport } from '@/types';

export function EvaluationTab({ report }: { report: Partial<BuildReport> | undefined }) {
  const evaluation = report?.gates?.evaluation?.evaluation;
  const [category, setCategory] = useState<string>('all');
  const [failedOnly, setFailedOnly] = useState(false);
  const cases = useMemo(
    () => (evaluation?.case_results ?? []).filter(item => (category === 'all' || item.category === category) && (!failedOnly || !item.passed)),
    [evaluation?.case_results, category, failedOnly],
  );

  if (!evaluation) {
    return (
      <EmptyState icon="target" title="No evaluation results yet">
        The generated evaluation suite runs after the tests pass: functional, retrieval, assessment and adversarial cases, each scored by the repository's own graders.
      </EmptyState>
    );
  }
  const categories = Object.entries(evaluation.by_category);
  const unsafeTarget = evaluation.thresholds.unsafe_actions ?? 0;

  return (
    <div className="stack">
      <section className="measures" aria-label="Evaluation metrics">
        <TargetMeter label="Task success" value={evaluation.task_success} target={evaluation.thresholds.task_success ?? null} source={`${evaluation.passed_cases}/${evaluation.cases} cases`} />
        <TargetMeter label="Tool accuracy" value={evaluation.tool_accuracy} target={evaluation.thresholds.tool_accuracy ?? null} source="tool-call micro F1" />
        <div className={`tile ${evaluation.unsafe_actions > unsafeTarget ? 'tile-bad' : 'tile-good'}`}>
          <span>Unsafe actions</span>
          <strong>{evaluation.unsafe_actions}</strong>
          <small>limit {unsafeTarget}, any side effect without a matching approval counts</small>
        </div>
      </section>

      <p className="help">
        {evaluation.mode === 'offline'
          ? 'Offline mode runs the deterministic model, so it measures routing, tool selection, approval gating and guardrails rather than language quality. Run python -m evals.run --live in the repository to score the configured model.'
          : `Live evaluation against ${evaluation.model}.`}
      </p>

      <div className="split">
        <section className="panel">
          <h3>By category</h3>
          <ul className="bars" aria-label="Pass rate by category">
            {categories.map(([name, counts]) => (
              <li key={name}>
                <span>{humanize(name)}</span>
                <span className="bar">
                  <span style={{ width: `${counts.cases ? (counts.passed / counts.cases) * 100 : 0}%` }} />
                </span>
                <span className="bar-value">
                  {counts.passed}/{counts.cases}
                </span>
              </li>
            ))}
          </ul>
        </section>
        <section className="panel">
          <h3>Thresholds</h3>
          <dl className="facts">
            {Object.entries(evaluation.thresholds).map(([name, value]) => (
              <div key={name}>
                <dt>{humanize(name)}</dt>
                <dd>{name === 'unsafe_actions' ? value : formatPercent(value)}</dd>
              </div>
            ))}
          </dl>
        </section>
      </div>

      <section className="panel">
        <div className="section-title">
          <h3>Cases</h3>
          <div className="toolbar toolbar-tight">
            <label className="select">
              <span className="sr-only">Category</span>
              <select value={category} onChange={event => setCategory(event.target.value)}>
                <option value="all">All categories</option>
                {categories.map(([name]) => (
                  <option key={name} value={name}>
                    {humanize(name)}
                  </option>
                ))}
              </select>
            </label>
            <label className="check">
              <input type="checkbox" checked={failedOnly} onChange={event => setFailedOnly(event.target.checked)} />
              Failed only
            </label>
          </div>
        </div>
        {cases.length === 0 ? (
          <p className="muted">{failedOnly ? 'Every case in this selection passed.' : 'No cases in this category.'}</p>
        ) : (
          <ul className="cases">
            {cases.map(item => (
              <li key={item.id} className={`case ${item.passed ? 'is-passed' : 'is-failed'}`}>
                <Icon name={item.passed ? 'check' : 'x'} />
                <span className="case-name">{item.id}</span>
                <span className="case-time">{humanize(item.category)}</span>
                {item.details.length ? (
                  <ul className="case-details">
                    {item.details.map(detail => (
                      <li key={detail}>{detail}</li>
                    ))}
                  </ul>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
