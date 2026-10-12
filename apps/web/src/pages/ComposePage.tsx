import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { stringify } from 'yaml';
import { api } from '@/api/client';
import { CopyButton, ErrorNotice, Notice } from '@/components/Feedback';
import { Icon } from '@/components/Icon';
import { PlanFlow, TopologyChecks } from '@/components/PlanFlow';
import { ModeBadge, SeverityBadge } from '@/components/Status';
import { useCompile, useCreateBuild, useSystem, useTemplates } from '@/hooks/queries';
import { useDebouncedValue } from '@/hooks/useDebouncedValue';
import { formatPercent, humanize, shortHash } from '@/lib/format';
import { buildPath, navigate } from '@/router';
import type { AgentSpec, AnalysisSummary, ArchitecturePlan, CompileEngine, ValidateResponse } from '@/types';

const DEFAULT_REQUIREMENT =
  'Build a property maintenance triage agent for our operations team. It should classify tenant requests, assess urgency, look up property details and maintenance policies, draft work orders and tenant emails, and require human approval before any external message or work order is sent. Use a local Qwen model, Postgres memory, and target at least 90% task success with zero unsafe actions.';
const MIN_REQUIREMENT = 24;

const ENGINES: Array<{ value: CompileEngine; label: string; detail: string }> = [
  { value: 'auto', label: 'Automatic', detail: 'Model-assisted when configured, deterministic otherwise' },
  { value: 'heuristic', label: 'Deterministic', detail: 'Same input, same specification, no model call' },
  { value: 'llm', label: 'Model-assisted', detail: 'The model drafts; safety invariants are re-applied' },
];

function toYaml(spec: AgentSpec): string {
  return stringify(spec, { indent: 2, lineWidth: 0 });
}

function newKey(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
}

function planBlockers(plan: ArchitecturePlan | null): string[] {
  if (!plan) return [];
  return [
    ...plan.checks.filter(check => !check.passed).map(check => check.title),
    ...plan.risk.findings.filter(finding => finding.blocking).map(finding => finding.title),
  ];
}

function Understanding({ analysis, warnings }: { analysis: AnalysisSummary | null; warnings: string[] }) {
  if (!analysis) return null;
  const notes = [...analysis.inferences, ...analysis.assumptions];
  return (
    <section className="panel understanding" aria-labelledby="understanding-title">
      <h3 id="understanding-title">What the compiler understood</h3>
      <dl className="facts">
        <div>
          <dt>Domain</dt>
          <dd>{humanize(analysis.domain)}</dd>
        </div>
        <div>
          <dt>Confidence</dt>
          <dd>{formatPercent(analysis.confidence)}</dd>
        </div>
        <div>
          <dt>Compiler</dt>
          <dd>{analysis.engine === 'llm' ? `Model-assisted (${analysis.model ?? 'model'})` : 'Deterministic'}</dd>
        </div>
      </dl>
      {notes.length ? (
        <ul className="notes">
          {notes.map(note => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      ) : null}
      {warnings.length ? (
        <Notice tone="warn" title="Review before building">
          <ul className="notes">
            {warnings.map(warning => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </Notice>
      ) : null}
    </section>
  );
}

function Contract({ spec }: { spec: AgentSpec }) {
  return (
    <section className="panel contract" aria-labelledby="contract-title">
      <h3 id="contract-title">Contract</h3>
      <p className="contract-objective">{spec.agent.objective}</p>
      <h4>Tools</h4>
      <ul className="tool-list">
        {spec.tools.map(tool => (
          <li key={tool.name}>
            <code>{tool.name}</code>
            <ModeBadge mode={tool.mode} approval={tool.mode === 'execute' || tool.approval_required || (tool.mode === 'draft' && spec.guardrails.external_messages.approval_required)} />
          </li>
        ))}
      </ul>
      <h4>Targets</h4>
      <dl className="facts">
        <div>
          <dt>Task success</dt>
          <dd>{formatPercent(spec.evaluation.task_success_target)}</dd>
        </div>
        <div>
          <dt>Tool accuracy</dt>
          <dd>{formatPercent(spec.evaluation.tool_accuracy_target)}</dd>
        </div>
        <div>
          <dt>Unsafe actions</dt>
          <dd>{spec.evaluation.unsafe_action_target}</dd>
        </div>
        <div>
          <dt>Adversarial cases</dt>
          <dd>{spec.evaluation.adversarial_cases}</dd>
        </div>
      </dl>
      <h4>Runtime</h4>
      <dl className="facts">
        <div>
          <dt>Model</dt>
          <dd>
            {spec.model.provider} / {spec.model.model}
          </dd>
        </div>
        <div>
          <dt>Memory</dt>
          <dd>{spec.memory.type === 'none' ? 'None' : `${spec.memory.type}, ${spec.memory.pii_retention_days}-day retention`}</dd>
        </div>
        <div>
          <dt>Retrieval</dt>
          <dd>{spec.retrieval.enabled ? spec.retrieval.sources.map(source => source.name).join(', ') : 'Off'}</dd>
        </div>
      </dl>
    </section>
  );
}

function Validation({ query, dirty }: { query: { data?: ValidateResponse; isFetching: boolean; error: unknown }; dirty: boolean }) {
  if (dirty || (query.isFetching && !query.data)) {
    return (
      <span className="editor-status is-checking">
        <Icon name="refresh" className="spin" /> Validating
      </span>
    );
  }
  if (query.error) return <span className="editor-status is-bad">Validation unavailable</span>;
  if (!query.data) return null;
  return query.data.valid ? (
    <span className="editor-status is-good">
      <Icon name="check" /> Valid, SHA-256 {shortHash(query.data.spec_hash)}
    </span>
  ) : (
    <span className="editor-status is-bad">
      <Icon name="x" /> {query.data.errors.length} {query.data.errors.length === 1 ? 'error' : 'errors'}
    </span>
  );
}

export function ComposePage({ templateId }: { templateId: string | null }) {
  const system = useSystem();
  const templates = useTemplates();
  const compile = useCompile();
  const createBuild = useCreateBuild();

  const template = templates.data?.find(item => item.id === templateId);
  const [draft, setDraft] = useState<string | null>(null);
  const requirement = draft ?? template?.requirement ?? DEFAULT_REQUIREMENT;
  const [engine, setEngine] = useState<CompileEngine>('auto');
  const [document, setDocument] = useState('');
  const [buildKey, setBuildKey] = useState(newKey);

  const debouncedDocument = useDebouncedValue(document, 450);
  const validation = useQuery({
    queryKey: ['validate', debouncedDocument],
    queryFn: ({ signal }) => api.validateDocument(debouncedDocument, signal),
    enabled: debouncedDocument.trim().length > 0,
    placeholderData: keepPreviousData,
    staleTime: Infinity,
    retry: false,
  });

  const llmAvailable = system.data?.compiler.engines.includes('llm') ?? false;
  const maxChars = system.data?.limits.max_requirement_chars ?? 12_000;
  const result = validation.data;
  const dirty = document !== debouncedDocument;
  const plan = result?.valid ? result.plan : null;
  const blockers = useMemo(() => planBlockers(plan), [plan]);
  const ready = Boolean(result?.valid && result.spec && result.spec_hash && plan) && !dirty && blockers.length === 0;

  const runCompile = () => {
    compile.mutate(
      { requirement, engine: llmAvailable ? engine : 'heuristic' },
      {
        onSuccess: response => {
          setDocument(toYaml(response.spec));
          setBuildKey(newKey());
          window.requestAnimationFrame(() => window.document.getElementById('specification')?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
        },
      },
    );
  };

  const runBuild = () => {
    if (!result?.spec || !result.spec_hash) return;
    createBuild.mutate(
      { spec: result.spec, specHash: result.spec_hash, idempotencyKey: `${result.spec_hash.slice(0, 16)}:${buildKey}` },
      { onSuccess: build => navigate(buildPath(build.id)) },
    );
  };

  const downloadYaml = () => {
    const blob = new Blob([document], { type: 'application/yaml' });
    const url = URL.createObjectURL(blob);
    const anchor = window.document.createElement('a');
    anchor.href = url;
    anchor.download = 'agent-spec.yaml';
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
  };

  const tooShort = requirement.trim().length < MIN_REQUIREMENT;

  return (
    <div className="page compose">
      <header className="page-head">
        <h1>Describe the agent you need</h1>
        <p>
          Write the requirement in plain language. AgentForge compiles it into a validated, hashed specification, shows you the architecture it will
          build, and only then generates, tests and signs the repository.
        </p>
      </header>

      <section className="panel requirement" aria-labelledby="requirement-title">
        <div className="section-title">
          <h2 id="requirement-title">Requirement</h2>
          <span className="counter">
            {requirement.length.toLocaleString()} / {maxChars.toLocaleString()}
          </span>
        </div>
        <label className="sr-only" htmlFor="requirement-input">
          Requirement
        </label>
        <textarea
          id="requirement-input"
          className="requirement-input"
          value={requirement}
          maxLength={maxChars}
          rows={7}
          onChange={event => setDraft(event.target.value)}
          aria-describedby="requirement-help"
        />
        <p id="requirement-help" className="help">
          Name the work the agent does, the systems it reads, the actions that need approval, the model and your quality bar.
        </p>
        {templates.data?.length ? (
          <div className="template-row" role="group" aria-label="Start from a template">
            {templates.data.map(item => (
              <button key={item.id} type="button" className={`pill ${item.requirement === requirement ? 'is-selected' : ''}`} onClick={() => setDraft(item.requirement)}>
                {item.title}
              </button>
            ))}
          </div>
        ) : null}
        <div className="requirement-actions">
          {llmAvailable ? (
            <fieldset className="segmented">
              <legend className="sr-only">Compiler</legend>
              {ENGINES.map(option => (
                <label key={option.value} title={option.detail} className={engine === option.value ? 'is-selected' : ''}>
                  <input type="radio" name="engine" value={option.value} checked={engine === option.value} onChange={() => setEngine(option.value)} />
                  {option.label}
                </label>
              ))}
            </fieldset>
          ) : (
            <span className="help">Deterministic compiler. The same requirement always produces the same specification.</span>
          )}
          <button type="button" className="button button-primary" onClick={runCompile} disabled={compile.isPending || tooShort}>
            {compile.isPending ? <Icon name="refresh" className="spin" /> : <Icon name="play" />}
            {compile.isPending ? 'Compiling' : 'Compile specification'}
          </button>
        </div>
        {compile.error ? <ErrorNotice error={compile.error} title="The requirement could not be compiled" /> : null}
      </section>

      {document ? (
        <section id="specification" className="spec" aria-labelledby="spec-title">
          <div className="section-title">
            <h2 id="spec-title">Specification</h2>
            <div className="actions">
              <CopyButton value={document} label="Copy YAML" />
              <button type="button" className="button button-quiet" onClick={downloadYaml}>
                <Icon name="download" />
                agent-spec.yaml
              </button>
            </div>
          </div>
          <div className="spec-grid">
            <div className="editor">
              <div className="editor-bar">
                <span>
                  <Icon name="edit" /> agent-spec.yaml
                </span>
                <Validation query={validation} dirty={dirty} />
              </div>
              {result && !result.valid && !dirty ? (
                <ul className="issues" aria-label="Validation errors">
                  {result.errors.map(issue => (
                    <li key={`${issue.loc}:${issue.message}`}>
                      <code>{issue.loc || 'document'}</code>
                      {issue.message}
                    </li>
                  ))}
                </ul>
              ) : null}
              <label className="sr-only" htmlFor="spec-editor">
                AgentSpec YAML
              </label>
              <textarea
                id="spec-editor"
                className="editor-input"
                spellCheck={false}
                value={document}
                aria-invalid={result ? !result.valid : undefined}
                onChange={event => setDocument(event.target.value)}
              />
              {validation.error ? <ErrorNotice error={validation.error} title="Validation failed" onRetry={() => void validation.refetch()} /> : null}
            </div>
            <div className="spec-side">
              <Understanding analysis={compile.data?.analysis ?? null} warnings={result?.valid ? result.warnings : (compile.data?.warnings ?? [])} />
              {result?.spec ? <Contract spec={result.spec} /> : null}
            </div>
          </div>
        </section>
      ) : null}

      {plan ? (
        <section className="architecture" aria-labelledby="architecture-title">
          <div className="section-title">
            <h2 id="architecture-title">Architecture</h2>
            <span className="help">Derived from the specification and verified before any code is generated.</span>
          </div>
          <div className="architecture-grid">
            <div className="panel">
              <PlanFlow plan={plan} />
            </div>
            <div className="architecture-side">
              <section className="panel">
                <h3>Verified properties</h3>
                <TopologyChecks plan={plan} />
              </section>
              <section className="panel">
                <h3>Risk register</h3>
                <ul className="risks">
                  {plan.risk.findings.map(finding => (
                    <li key={finding.id}>
                      <SeverityBadge severity={finding.severity} />
                      <div>
                        <strong>{finding.title}</strong>
                        <span>{finding.mitigation}</span>
                      </div>
                      <span className={`risk-status is-${finding.status}`}>{finding.status}</span>
                    </li>
                  ))}
                </ul>
              </section>
            </div>
          </div>
        </section>
      ) : null}

      {document ? (
        <div className="commit-bar" role="region" aria-label="Start build">
          <div>
            <strong>{result?.spec ? humanize(result.spec.agent.name) : 'Specification'}</strong>
            <span>
              {ready
                ? `Ready to generate, test, evaluate and sign. Spec ${shortHash(result?.spec_hash)}.`
                : blockers.length
                  ? `Blocked: ${blockers.join('; ')}`
                  : result && !result.valid
                    ? `${result.errors.length} validation ${result.errors.length === 1 ? 'error' : 'errors'} in agent-spec.yaml.`
                    : 'Validating the specification.'}
            </span>
          </div>
          <button type="button" className="button button-primary button-large" disabled={!ready || createBuild.isPending} onClick={runBuild}>
            {createBuild.isPending ? <Icon name="refresh" className="spin" /> : <Icon name="play" />}
            {createBuild.isPending ? 'Starting build' : 'Generate and verify'}
          </button>
        </div>
      ) : null}
      {createBuild.error ? <ErrorNotice error={createBuild.error} title="The build could not be started" /> : null}
    </div>
  );
}
