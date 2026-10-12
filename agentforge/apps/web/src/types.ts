export type ToolMode = 'read' | 'draft' | 'execute';
export type BuildStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled';
export type StageStatus = 'pending' | 'running' | 'passed' | 'failed' | 'skipped';

export interface AgentSpec {
  version: '1.0';
  agent: {
    name: string;
    objective: string;
    description: string;
  };
  model: {
    provider: 'local' | 'openai' | 'anthropic';
    model: string;
    temperature: number;
  };
  tools: Array<{
    name: string;
    mode: ToolMode;
    approval_required: boolean;
  }>;
  retrieval: {
    enabled: boolean;
    sources: string[];
    citations_required: boolean;
  };
  workflow: string[];
  guardrails: {
    external_messages: { approval_required: boolean };
    tool_execution: { allowlist_only: boolean; timeout_seconds: number };
    prompt_injection: { action: 'block_and_log' | 'human_review' };
  };
  memory: {
    type: 'postgres' | 'sqlite' | 'none';
    namespace: string;
    pii_retention_days: number;
  };
  evaluation: {
    task_success_target: number;
    tool_accuracy_target: number;
    unsafe_action_target: number;
    adversarial_cases: number;
  };
}

export interface CompiledSpec {
  spec: AgentSpec;
  spec_hash: string;
  warnings: string[];
}

export interface PipelineStage {
  key: string;
  name: string;
  status: StageStatus;
  progress: number;
  started_at: string | null;
  finished_at: string | null;
  summary: string | null;
}

export interface BuildMetrics {
  task_success: number;
  tool_accuracy: number;
  unsafe_actions: number;
  test_coverage: number;
  tests_passed: number;
}

export interface Build {
  id: string;
  status: BuildStatus;
  agent_name: string;
  spec_hash: string;
  progress: number;
  current_stage: string | null;
  stages: PipelineStage[];
  logs: string[];
  metrics: BuildMetrics | null;
  artifact_ready: boolean;
  error: string | null;
  created_at: string;
  updated_at: string;
}

