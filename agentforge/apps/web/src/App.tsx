import { useEffect, useMemo, useState } from 'react';
import { stringify as toYaml } from 'yaml';
import { api, ApiError } from '@/api/client';
import { Icon } from '@/components/Icon';
import { useBuild, useCompileSpec, useCreateBuild } from '@/hooks/useAgentBuild';
import type { AgentSpec, Build, PipelineStage } from '@/types';

const initialRequirement = 'Build a property maintenance triage agent for our operations team. It should classify tenant requests, assess urgency, look up property details and maintenance policies, draft work orders and tenant emails, and require human approval before any external message or work order is sent. Use a local Qwen model, Postgres memory, and target at least 90% task success with zero unsafe actions.';

const templates = {
  'Customer support': 'Build a customer support agent for a B2B SaaS company. It should classify incoming tickets, search product documentation, check account status, draft helpful replies, and escalate billing or security issues to a human. Require approval before sending any reply. Use OpenAI, Postgres memory, and target 92% task success with zero unsafe actions.',
  'Research analyst': 'Build a market research analyst that takes a company or sector, searches approved sources, extracts evidence, compares competitors, and produces a cited briefing. It may never invent a citation and must flag low-confidence claims for human review. Use a local Qwen model with vector retrieval and target 90% factual accuracy.',
  Operations: 'Build an operations incident coordinator. It should classify incident reports, retrieve the relevant runbook, identify owners, prepare a response plan, and draft status updates. Never execute infrastructure changes and require human approval before external communication. Use Postgres memory and target zero unsafe actions.',
};

const repositoryTree = [
  ['src/', 0, true], ['agent/', 1, true], ['graph.py', 2, false], ['state.py', 2, false], ['prompts.py', 2, false],
  ['tools/', 1, true], ['registry.py', 2, false], ['adapters.py', 2, false], ['rag/', 1, true], ['retriever.py', 2, false],
  ['memory/', 1, true], ['store.py', 2, false], ['api/', 1, true], ['main.py', 2, false], ['tests/', 0, true],
  ['unit/', 1, true], ['integration/', 1, true], ['agent/', 1, true], ['evals/', 0, true], ['dataset.json', 1, false],
  ['graders.py', 1, false], ['Dockerfile', 0, false], ['compose.yaml', 0, false], ['pyproject.toml', 0, false],
  ['agent-spec.yaml', 0, false], ['architecture.md', 0, false], ['README.md', 0, false],
] as const;

function formatError(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error && error.message.includes('fetch')) return 'The AgentForge API is unavailable. Start the stack with docker compose up --build.';
  return error instanceof Error ? error.message : 'An unexpected error occurred.';
}

function Sidebar({ open, onClose }: { open: boolean; onClose: () => void }) {
  const nav = [
    ['plus', 'New build'], ['builds', 'Builds'], ['file', 'AgentSpecs'],
    ['tools', 'Tool registry'], ['chart', 'Evaluations'], ['shield', 'Security'],
  ] as const;
  return (
    <aside className={`sidebar ${open ? 'open' : ''}`} aria-label="Primary navigation">
      <a className="brand" href="#main" onClick={onClose}>
        <span className="brand-mark" aria-hidden="true"><svg viewBox="0 0 40 40"><path d="M8 29.5 19.7 8 32 29.5h-6.8l-2.1-4.2h-7.2l3.3-6h.9l-1.8-3.8-7.5 14H8Z" fill="currentColor"/><path d="M21.7 29.5h10.5l-5.3-9.2-5.2 9.2Z" fill="#B6F23D"/></svg></span>
        <span>AgentForge</span>
      </a>
      <nav className="nav-stack">
        <p className="nav-label">Workspace</p>
        {nav.map(([icon, label], index) => <button key={label} className={`nav-item ${index === 0 ? 'active' : ''}`} onClick={onClose}><Icon name={icon}/><span>{label}</span>{label === 'Builds' && <span className="count">0</span>}</button>)}
      </nav>
      <div className="sidebar-foot">
        <div className="sandbox-card">
          <div className="sandbox-top"><span className="pulse"/><span>Build services</span></div>
          <div className="usage-row"><span>API · worker · sandbox</span><span>Docker</span></div>
          <div className="usage-track"><span/></div>
        </div>
        <div className="account-button"><span className="avatar">AF</span><span className="account-copy"><strong>Local workspace</strong><small>Private environment</small></span></div>
      </div>
    </aside>
  );
}

function CompilerContract() {
  return (
    <aside className="contract-card panel">
      <div className="panel-head compact"><div><span className="step-number">↳</span><h2>Compiler contract</h2></div></div>
      <p>Raw text is never passed to the code generator. The API validates a typed contract first.</p>
      <div className="contract-flow">
        <div className="contract-node"><span className="node-icon amber">Aa</span><div><strong>Your requirement</strong><small>untrusted natural language</small></div></div>
        <div className="flow-line"><span/></div>
        <div className="contract-node emphasized"><span className="node-icon lime">{'{ }'}</span><div><strong>AgentSpec v1</strong><small>Pydantic-validated and hashed</small></div><span className="verified">required</span></div>
        <div className="flow-line"><span/></div>
        <div className="contract-node"><span className="node-icon violet">&lt;/&gt;</span><div><strong>Generated system</strong><small>derived only from the spec</small></div></div>
      </div>
      <div className="contract-rule"><Icon name="shield"/><span><strong>Hard boundary</strong>No arbitrary code generation from user text.</span></div>
    </aside>
  );
}

function RequirementForm({ requirement, onChange, onCompile, pending }: { requirement: string; onChange: (value: string) => void; onCompile: () => void; pending: boolean }) {
  return (
    <section className="requirement-card panel">
      <div className="panel-head"><div><span className="step-number">01</span><h2>Requirement</h2></div><span className="status-chip neutral">{pending ? 'Analysing' : 'Draft'}</span></div>
      <label htmlFor="requirement">Natural language brief</label>
      <div className="textarea-wrap">
        <textarea id="requirement" value={requirement} onChange={event => onChange(event.target.value)} maxLength={12000} rows={7}/>
        <div className="textarea-meta"><span>{requirement.length.toLocaleString()} / 12,000</span><span>Natural language</span></div>
      </div>
      <div className="templates-row"><span>Try a template</span>{Object.entries(templates).map(([name, value]) => <button key={name} className="template-pill" onClick={() => onChange(value)}>{name}</button>)}</div>
      <div className="compile-row">
        <div className="privacy-note"><Icon name="lock"/><span>Processed inside your private stack</span></div>
        <button className={`primary-button ${pending ? 'loading' : ''}`} onClick={onCompile} disabled={pending || requirement.trim().length < 24}><span>{pending ? 'Compiling…' : 'Compile requirement'}</span><Icon name="arrow"/></button>
      </div>
    </section>
  );
}

function SpecReview({ spec, specHash, onRun, pending }: { spec: AgentSpec; specHash: string; onRun: () => void; pending: boolean }) {
  const [format, setFormat] = useState<'yaml' | 'json'>('yaml');
  const source = format === 'yaml' ? toYaml(spec, { indent: 2 }) : JSON.stringify(spec, null, 2);
  const copy = () => { void navigator.clipboard.writeText(source); };
  return (
    <section className="spec-section">
      <div className="section-heading"><div><span className="step-number dark">02</span><div><h2>Review AgentSpec</h2><p>The validated contract controls every downstream decision.</p></div></div><button className="ghost-button" onClick={copy}><Icon name="copy"/>Copy</button></div>
      <div className="spec-grid">
        <div className="spec-editor panel">
          <div className="editor-bar"><div className="file-name"><span className="yaml-icon">Y</span>agent-spec.{format}</div><div className="format-switch"><button className={format === 'yaml' ? 'active' : ''} onClick={() => setFormat('yaml')}>YAML</button><button className={format === 'json' ? 'active' : ''} onClick={() => setFormat('json')}>JSON</button></div></div>
          <pre id="specCode" tabIndex={0}>{source}</pre>
          <div className="validation-bar"><span><Icon name="check"/>Schema valid</span><span>SHA-256 {specHash.slice(0, 12)}…</span></div>
        </div>
        <div className="spec-summary">
          <div className="summary-card"><span className="summary-label">Identity</span><strong>{spec.agent.name}</strong><small>{spec.agent.objective}</small></div>
          <div className="summary-card"><span className="summary-label">Capabilities</span><div className="chip-list">{spec.tools.map(tool => <span key={tool.name}>{tool.name}</span>)}</div></div>
          <div className="summary-card"><span className="summary-label">Governance</span><div className="guardrail-line"><span className="shield-small">✓</span><div><strong>Human approval</strong><small>External actions are draft-only</small></div></div><div className="guardrail-line"><span className="shield-small">✓</span><div><strong>Zero unsafe actions</strong><small>Blocking evaluation target</small></div></div></div>
          <button className="run-button" onClick={onRun} disabled={pending}><span><small>Next</small>{pending ? 'Queueing build…' : 'Generate & test agent'}</span><Icon name="play"/></button>
        </div>
      </div>
    </section>
  );
}

function StageNode({ stage, index }: { stage: PipelineStage; index: number }) {
  const active = stage.status === 'running';
  const done = stage.status === 'passed';
  return <div className={`pipeline-node ${active ? 'active' : ''} ${done ? 'done' : ''}`}><div className="pipeline-node-top"><span className="pipeline-node-number">{String(index + 1).padStart(2, '0')}</span><span className="pipeline-state">{done ? '✓' : active ? '•' : ''}</span></div><strong>{stage.name}</strong><small>{stage.summary ?? stage.status}</small></div>;
}

function Pipeline({ build }: { build: Build }) {
  const current = build.stages.find(stage => stage.status === 'running');
  return (
    <section className="pipeline-section">
      <div className="section-heading"><div><span className="step-number dark">03</span><div><h2>Engineering pipeline</h2><p>Durable worker execution with persisted progress and logs.</p></div></div><span className="elapsed">{build.status.toUpperCase()}</span></div>
      <div className="pipeline-shell panel"><div className="pipeline-layout">
        <div className="pipeline-map">{build.stages.map((stage, index) => <StageNode key={stage.key} stage={stage} index={index}/>)}</div>
        <div className="pipeline-detail">
          <div className="detail-head"><div><span className="live-dot"/><strong>{current?.name ?? (build.status === 'succeeded' ? 'Build complete' : build.current_stage ?? 'Queued')}</strong></div><span>{Math.round(build.progress)}%</span></div>
          <div className="terminal" aria-live="polite">{build.logs.length ? build.logs.map((line, index) => <div className={`log-line ${line.includes('passed') || line.includes('complete') ? 'success' : ''}`} key={`${index}-${line}`}><span>{String(index + 1).padStart(2, '0')}</span><span>{line}</span></div>) : <div className="log-line"><span>00</span><span>Waiting for worker…</span></div>}</div>
          <div className="test-meter"><div className="meter-copy"><span>{current?.summary ?? build.current_stage ?? 'Preparing'}</span><strong>{Math.round(build.progress)}%</strong></div><div className="meter-track"><span style={{ width: `${build.progress}%` }}/></div></div>
        </div>
      </div></div>
    </section>
  );
}

function Results({ build }: { build: Build }) {
  const metrics = build.metrics!;
  return (
    <section className="results-section">
      <div className="success-banner"><div className="success-icon"><Icon name="check"/></div><div><span>BUILD PASSED</span><h2>Your agent repository is ready</h2><p>Generated, linted, tested, evaluated, and security-validated by the worker.</p></div><div className="success-meta"><span>Build</span><strong>{build.id.slice(0, 8)}</strong></div></div>
      <div className="metrics-grid">
        <div className="metric-card"><span className="metric-icon lime"><Icon name="chart"/></span><div><span>Task success</span><strong>{(metrics.task_success * 100).toFixed(1)}<small>%</small></strong><em>Target satisfied</em></div></div>
        <div className="metric-card"><span className="metric-icon blue"><Icon name="tools"/></span><div><span>Tool accuracy</span><strong>{(metrics.tool_accuracy * 100).toFixed(1)}<small>%</small></strong><em>Typed tool suite</em></div></div>
        <div className="metric-card"><span className="metric-icon green"><Icon name="shield"/></span><div><span>Unsafe actions</span><strong>{metrics.unsafe_actions}</strong><em>Adversarial cases passed</em></div><span className="passed-pill">Passed</span></div>
        <div className="metric-card"><span className="metric-icon violet"><Icon name="file"/></span><div><span>Test coverage</span><strong>{(metrics.test_coverage * 100).toFixed(1)}<small>%</small></strong><em>{metrics.tests_passed} tests passing</em></div></div>
      </div>
      <div className="artifact-grid">
        <div className="artifact-panel panel"><div className="artifact-head"><div><h3>Generated repository</h3><p>{build.agent_name.replaceAll('_', '-')}-agent/</p></div><span className="file-total">production template</span></div><div className="file-tree">{repositoryTree.map(([name, depth, folder], index) => <div className={`tree-row ${folder ? 'folder' : ''}`} style={{ paddingLeft: depth * 16 }} key={`${index}-${name}`}><Icon name={folder ? 'builds' : 'file'}/><span>{name}</span></div>)}</div></div>
        <div className="delivery-panel panel"><span className="delivery-kicker">DELIVERY</span><h3>Ship your agent</h3><p>The artifact contains source, tests, evals, Docker assets, CI, architecture, and the immutable AgentSpec.</p><a className="download-button" href={api.artifactUrl(build.id)} download><Icon name="download"/><span><strong>Download source</strong><small>Verified ZIP artifact</small></span></a><div className="hash-row"><span>Spec SHA-256</span><code>{build.spec_hash.slice(0, 8)}…{build.spec_hash.slice(-8)}</code></div></div>
      </div>
    </section>
  );
}

export function App() {
  const [requirement, setRequirement] = useState(initialRequirement);
  const [compiled, setCompiled] = useState<{ spec: AgentSpec; specHash: string } | null>(null);
  const [buildId, setBuildId] = useState<string | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);
  const compile = useCompileSpec();
  const createBuild = useCreateBuild();
  const buildQuery = useBuild(buildId);
  const build = buildQuery.data;
  const error = compile.error ?? createBuild.error ?? buildQuery.error;
  const buildNumber = useMemo(() => compiled ? compiled.specHash.slice(0, 6).toUpperCase() : 'NEW', [compiled]);

  useEffect(() => {
    if (build?.status === 'failed') document.title = 'Build failed — AgentForge';
    else if (build?.status === 'succeeded') document.title = 'Build ready — AgentForge';
    else document.title = 'AgentForge — Agent Engineering Workbench';
  }, [build?.status]);

  const handleCompile = async () => {
    setCompiled(null); setBuildId(null);
    const result = await compile.mutateAsync(requirement);
    setCompiled({ spec: result.spec, specHash: result.spec_hash });
    requestAnimationFrame(() => document.querySelector('.spec-section')?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
  };

  const handleBuild = async () => {
    if (!compiled) return;
    const result = await createBuild.mutateAsync({ spec: compiled.spec, specHash: compiled.specHash });
    setBuildId(result.id);
    requestAnimationFrame(() => document.querySelector('.pipeline-section')?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
  };

  return (
    <div className="app-shell">
      <Sidebar open={mobileOpen} onClose={() => setMobileOpen(false)}/>
      <main className="main" id="main">
        <header className="topbar"><button className="mobile-menu" onClick={() => setMobileOpen(value => !value)} aria-label="Toggle navigation"><Icon name="menu"/></button><div className="crumbs"><span>AgentForge</span><b>/</b><strong>New build</strong></div><div className="top-actions"><span className="runtime-badge"><span className="pulse"/>FastAPI connected</span><a className="docs-button" href="/api/docs" target="_blank" rel="noreferrer">API docs <Icon name="arrow"/></a></div></header>
        <div className="workspace">
          <div className="intro-row"><div><div className="eyebrow"><span/>deterministic agent engineering</div><h1>What should your agent do?</h1><p>Describe the outcome in plain language. The API compiles it into a validated, hashed contract before any source artifact is generated.</p></div><div className="build-id"><span>BUILD</span><code>AF-{buildNumber}</code></div></div>
          {error && <div className="error-banner" role="alert"><Icon name="shield"/><div><strong>Could not complete the request</strong><span>{formatError(error)}</span></div><button onClick={() => { compile.reset(); createBuild.reset(); void buildQuery.refetch(); }}><Icon name="refresh"/>Retry</button></div>}
          <div className="builder-grid"><RequirementForm requirement={requirement} onChange={setRequirement} onCompile={() => void handleCompile()} pending={compile.isPending}/><CompilerContract/></div>
          {compiled && <SpecReview spec={compiled.spec} specHash={compiled.specHash} onRun={() => void handleBuild()} pending={createBuild.isPending}/>} 
          {build && <Pipeline build={build}/>} 
          {build?.status === 'succeeded' && build.metrics && build.artifact_ready && <Results build={build}/>} 
          {build?.status === 'failed' && <div className="failed-panel panel"><Icon name="shield"/><div><h2>Build failed safely</h2><p>{build.error ?? 'A quality gate did not pass. Inspect the persisted pipeline logs above.'}</p></div></div>}
        </div>
      </main>
    </div>
  );
}

