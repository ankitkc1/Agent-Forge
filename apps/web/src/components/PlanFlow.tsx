import { Icon } from '@/components/Icon';
import { ModeBadge } from '@/components/Status';
import type { ArchitecturePlan, PlanEdge, PlanNode, ToolBinding } from '@/types';

const GROUP: Record<string, string> = {
  guard_input: 'platform',
  finalize: 'platform',
  classify: 'understand',
  assess: 'understand',
  analyze: 'understand',
  retrieve: 'evidence',
  lookup: 'evidence',
  verify: 'evidence',
  draft: 'propose',
  safety_check: 'control',
  execute: 'act',
  respond: 'respond',
};

const KIND_LABEL: Record<string, string> = {
  guard_input: 'input guard',
  finalize: 'audit',
  safety_check: 'policy check',
  human_approval: 'approval gate',
};

const EXIT_LABEL: Record<string, string> = {
  blocked: 'If blocked',
  rejected: 'If rejected',
};

function exitsOf(node: PlanNode, edges: PlanEdge[], titles: Map<string, string>) {
  return edges
    .filter(edge => edge.source === node.id && edge.condition && edge.condition in EXIT_LABEL)
    .map(edge => ({ label: EXIT_LABEL[edge.condition!]!, target: titles.get(edge.target) ?? edge.target }));
}

function ToolChips({ names, bindings }: { names: string[]; bindings: Map<string, ToolBinding> }) {
  return (
    <ul className="chips" aria-label="Tools">
      {names.map(name => {
        const binding = bindings.get(name);
        return (
          <li key={name} className="chip">
            <code>{name}</code>
            {binding ? <ModeBadge mode={binding.mode} approval={binding.approval_required} /> : null}
          </li>
        );
      })}
    </ul>
  );
}

/**
 * The agent's control flow as the generated LangGraph will execute it: the main path top to
 * bottom, conditional exits on the right, and the human approval gate drawn across the flow so
 * it is visible that every side effect sits behind it.
 */
export function PlanFlow({ plan }: { plan: ArchitecturePlan }) {
  const nodes = [...plan.nodes].sort((a, b) => a.order - b.order);
  const titles = new Map(nodes.map(node => [node.id, node.title]));
  const bindings = new Map(plan.tools.map(tool => [tool.name, tool]));
  const actionTools = plan.tools.filter(tool => tool.mode !== 'read').map(tool => tool.name);

  return (
    <ol className="flow" aria-label={`${plan.agent} workflow`}>
      {nodes.map(node => {
        const exits = exitsOf(node, plan.edges, titles);
        if (node.kind === 'human_approval') {
          return (
            <li key={node.id} className="flow-gate">
              <div className="gate-band">
                <Icon name="user" />
                <div>
                  <strong>{node.title}</strong>
                  <span>Nothing below this line runs until a reviewer approves the exact proposed actions.</span>
                </div>
                {exits.map(exit => (
                  <span className="flow-exit" key={exit.label}>
                    {exit.label} <Icon name="arrow" /> {exit.target}
                  </span>
                ))}
              </div>
            </li>
          );
        }
        const group = node.side_effects ? 'act' : (GROUP[node.kind] ?? 'understand');
        const tools = node.kind === 'execute' && node.tools.length === 0 ? actionTools : node.tools;
        return (
          <li key={node.id} className={`flow-node group-${group}`}>
            <span className="flow-dot" aria-hidden="true" />
            <div className="flow-body">
              <div className="flow-head">
                <strong>{node.title}</strong>
                <code className="flow-id">{node.id}</code>
                <span className="flow-kind">{KIND_LABEL[node.kind] ?? node.kind.replaceAll('_', ' ')}</span>
                {node.side_effects ? (
                  <span className="flow-effects">
                    <Icon name="alert" /> Side effects
                  </span>
                ) : null}
              </div>
              {node.description ? <p>{node.description}</p> : null}
              {tools.length ? <ToolChips names={tools} bindings={bindings} /> : null}
              {node.sources.length ? (
                <ul className="chips" aria-label="Knowledge sources">
                  {node.sources.map(source => (
                    <li key={source} className="chip chip-source">
                      <Icon name="file" />
                      <code>{source}</code>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
            {exits.length ? (
              <div className="flow-exits">
                {exits.map(exit => (
                  <span className="flow-exit" key={exit.label}>
                    {exit.label} <Icon name="arrow" /> {exit.target}
                  </span>
                ))}
              </div>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}

export function TopologyChecks({ plan }: { plan: ArchitecturePlan }) {
  return (
    <ul className="checklist">
      {plan.checks.map(check => (
        <li key={check.id} className={check.passed ? 'is-pass' : 'is-fail'}>
          <Icon name={check.passed ? 'check' : 'x'} />
          <div>
            <strong>{check.title}</strong>
            <span>{check.detail}</span>
          </div>
        </li>
      ))}
    </ul>
  );
}
