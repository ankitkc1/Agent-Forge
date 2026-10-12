// Contracts mirrored from the AgentForge API (services/api/app/schemas). Keep in sync.

export type ToolMode = 'read' | 'draft' | 'execute';
export type StepKind =
  | 'classify'
  | 'assess'
  | 'retrieve'
  | 'lookup'
  | 'analyze'
  | 'draft'
  | 'safety_check'
  | 'verify'
  | 'human_approval'
  | 'execute'
  | 'respond';
export type Severity = 'info' | 'low' | 'medium' | 'high' | 'critical';

// ----------------------------------------------------------------------------- AgentSpec v1

export interface ToolParameter {
  name: string;
  type: 'string' | 'integer' | 'number' | 'boolean';
  description: string;
  required: boolean;
}

export interface ToolSpec {
  name: string;
  description: string;
  mode: ToolMode;
  approval_required: boolean;
  timeout_seconds: number | null;
  inputs: ToolParameter[];
}

export interface LabelSpec {
  name: string;
  description: string;
  hints: string[];
}

export interface WorkflowStep {
  id: string;
  kind: StepKind;
  description: string;
  tools: string[];
  sources: string[];
  labels: LabelSpec[];
  dimension: string | null;
  review: 'when_required' | 'always' | null;
}

export interface AgentSpec {
  version: '1.0';
  agent: { name: string; domain: string; objective: string; description: string; constraints: string[] };
  model: { provider: 'local' | 'openai' | 'anthropic'; model: string; temperature: number; max_output_tokens: number };
  tools: ToolSpec[];
  retrieval: {
    enabled: boolean;
    sources: Array<{ name: string; description: string }>;
    top_k: number;
    min_score: number;
    citations_required: boolean;
    chunk_size: number;
    chunk_overlap: number;
    embeddings: 'hashing' | 'openai' | 'ollama';
    store: 'memory' | 'pgvector';
  };
  workflow: WorkflowStep[];
  guardrails: {
    external_messages: { approval_required: boolean };
    tool_execution: { allowlist_only: boolean; timeout_seconds: number; max_calls_per_run: number };
    prompt_injection: { action: 'block_and_log' | 'human_review'; scan_retrieved_content: boolean };
    pii: { redact_logs: boolean; redact_memory: boolean };
  };
  memory: { type: 'postgres' | 'sqlite' | 'none'; namespace: string; pii_retention_days: number; conversation_window: number };
  evaluation: {
    task_success_target: number;
    tool_accuracy_target: number;
    unsafe_action_target: number;
    adversarial_cases: number;
  };
}

export type CompileEngine = 'auto' | 'heuristic' | 'llm';

export interface AnalysisSummary {
  engine: 'heuristic' | 'llm';
  model: string | null;
  domain: string;
  confidence: number;
  assumptions: string[];
  inferences: string[];
  requirement_sha256: string;
}

export interface CompileResponse {
  spec: AgentSpec;
  spec_hash: string;
  warnings: string[];
  analysis: AnalysisSummary | null;
}

export interface SpecIssue {
  loc: string;
  message: string;
}

export interface ValidateResponse {
  valid: boolean;
  spec: AgentSpec | null;
  spec_hash: string | null;
  errors: SpecIssue[];
  warnings: string[];
  plan: ArchitecturePlan | null;
}

// --------------------------------------------------------------------------- architecture plan

export interface PlanNode {
  id: string;
  kind: string;
  title: string;
  description: string;
  tools: string[];
  sources: string[];
  platform: boolean;
  side_effects: boolean;
  order: number;
}

export interface PlanEdge {
  source: string;
  target: string;
  condition: string | null;
}

export interface ToolBinding {
  name: string;
  description: string;
  mode: ToolMode;
  approval_required: boolean;
  timeout_seconds: number;
  inputs: ToolParameter[];
  used_by: string[];
  phases: string[];
}

export interface TopologyCheck {
  id: string;
  title: string;
  passed: boolean;
  detail: string;
}

export interface RiskFinding {
  id: string;
  severity: Severity;
  title: string;
  detail: string;
  mitigation: string;
  status: 'mitigated' | 'accepted' | 'open';
  blocking: boolean;
}

export interface ArchitecturePlan {
  schema_version: string;
  agent: string;
  nodes: PlanNode[];
  edges: PlanEdge[];
  tools: ToolBinding[];
  checks: TopologyCheck[];
  risk: { level: Severity; blocking: boolean; findings: RiskFinding[] };
  components: Array<{ id: string; title: string; technology: string; detail: string }>;
  mermaid: string;
}

// ---------------------------------------------------------------------------------- builds

export type BuildStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled';
export type StageStatus = 'pending' | 'running' | 'passed' | 'failed' | 'skipped' | 'cancelled';
export const TERMINAL_STATUSES: ReadonlySet<BuildStatus> = new Set(['succeeded', 'failed', 'cancelled']);

export interface PipelineStage {
  key: string;
  name: string;
  status: StageStatus;
  progress: number;
  started_at: string | null;
  finished_at: string | null;
  summary: string | null;
  attempts: number;
}

export interface BuildMetrics {
  task_success: number;
  tool_accuracy: number;
  unsafe_actions: number;
  test_coverage: number;
  tests_passed: number;
  tests_total: number;
  tests_failed: number;
  eval_cases: number;
  adversarial_cases: number;
  security_findings: number;
  repair_attempts: number;
  files: number;
  eval_mode: string;
}

export interface BuildEvent {
  id: number;
  created_at: string;
  level: string;
  stage: string | null;
  message: string;
}

export interface BuildSummary {
  id: string;
  status: BuildStatus;
  agent_name: string;
  spec_hash: string;
  progress: number;
  current_stage: string | null;
  metrics: BuildMetrics | null;
  artifact_ready: boolean;
  error: string | null;
  requested_by: string | null;
  attempt: number;
  parent_build_id: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
  duration_seconds: number | null;
}

export interface Build extends BuildSummary {
  stages: PipelineStage[];
  logs: string[];
  events: BuildEvent[];
  artifact_sha256: string | null;
  artifact_size: number | null;
  agentforge_version: string | null;
  cancel_requested: boolean;
}

export interface BuildPage {
  items: BuildSummary[];
  next_cursor: string | null;
}

export interface FileEntry {
  path: string;
  size: number;
  sha256: string | null;
  evidence: boolean;
}

export interface FileContent {
  path: string;
  size: number;
  content: string;
  language: string;
  truncated: boolean;
}

// ---------------------------------------------------------------------------- build report

export interface CommandSummary {
  command: string;
  exit_code: number;
  duration_seconds: number;
  timed_out: boolean;
  output_tail: string;
}

export interface TestCaseResult {
  id: string;
  outcome: 'passed' | 'failed' | 'skipped' | 'error';
  duration_seconds: number;
  message: string | null;
}

export interface TestSummary {
  total: number;
  passed: number;
  failed: number;
  skipped: number;
  errors: number;
  duration_seconds: number;
}

export interface CoverageSummary {
  percent: number;
  covered_lines: number;
  total_lines: number;
  files: Array<{ path: string; percent: number; missing_lines: number }>;
}

export interface EvalCaseResult {
  id: string;
  category: string;
  passed: boolean;
  details: string[];
}

export interface EvalSummary {
  mode: string;
  model: string;
  passed: boolean;
  task_success: number;
  tool_accuracy: number;
  unsafe_actions: number;
  cases: number;
  passed_cases: number;
  thresholds: Record<string, number>;
  by_category: Record<string, { cases: number; passed: number }>;
  case_results: EvalCaseResult[];
}

export type GateStatus = 'passed' | 'failed' | 'error' | 'skipped' | 'warning';

export interface GateResult {
  name: string;
  status: GateStatus;
  attempts: number;
  duration_seconds: number;
  summary: string;
  commands: CommandSummary[];
  tests: TestSummary | null;
  test_cases: TestCaseResult[];
  coverage: CoverageSummary | null;
  evaluation: EvalSummary | null;
}

export interface RepairAttempt {
  number: number;
  gate: string;
  strategy: string;
  outcome: 'changed' | 'unchanged' | 'rejected' | 'error';
  changed_files: string[];
  detail: string;
}

export interface SecurityFinding {
  rule_id: string;
  severity: Severity;
  title: string;
  path: string | null;
  line: number | null;
  detail: string;
  source: 'agentforge' | 'bandit';
  blocking: boolean;
}

export interface SecurityReport {
  status: 'passed' | 'failed';
  summary: Record<Severity, number>;
  findings: SecurityFinding[];
  checks: string[];
  files_scanned: number;
}

export interface PackageReport {
  archive_sha256: string;
  size_bytes: number;
  files: number;
  source_digest: string;
  signature: { algorithm: string; key_id: string; signed: boolean } | null;
  sbom_components: number;
}

export interface BuildReport {
  schema_version: string;
  build_id: string;
  agent: string;
  spec_hash: string;
  agentforge_version: string;
  sandbox: string | null;
  plan: ArchitecturePlan | null;
  generation: { files: number; bytes: number; formatted: boolean; notes: string[] } | null;
  gates: Partial<Record<'quality' | 'tests' | 'evaluation', GateResult>>;
  repairs: RepairAttempt[];
  security: SecurityReport | null;
  package: PackageReport | null;
  timings: Record<string, number>;
  notes: string[];
}

// ---------------------------------------------------------------------------------- system

export interface SystemInfo {
  version: string;
  environment: string;
  auth_mode: 'none' | 'api_key' | 'trusted_header';
  compiler: { engines: Array<'heuristic' | 'llm'>; llm_provider: string; domains: string[] };
  sandbox: { backend: 'process' | 'docker'; timeout_seconds: number };
  dispatch: 'celery' | 'inline';
  repair: { max_attempts: number; llm: boolean };
  signing: { enabled: boolean; key_id: string | null };
  limits: { max_requirement_chars: number; max_active_builds: number; build_retention_days: number };
  step_kinds: StepKind[];
}

export interface RequirementTemplate {
  id: string;
  title: string;
  domain: string;
  summary: string;
  requirement: string;
}
