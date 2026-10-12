import { CopyButton, EmptyState } from '@/components/Feedback';
import { PlanFlow, TopologyChecks } from '@/components/PlanFlow';
import { ModeBadge, SeverityBadge } from '@/components/Status';
import type { BuildReport } from '@/types';

export function ArchitectureTab({ report }: { report: Partial<BuildReport> | undefined }) {
  const plan = report?.plan;
  if (!plan) {
    return (
      <EmptyState icon="graph" title="No architecture yet">
        The planner runs first; its verified plan appears here within a second of the build starting.
      </EmptyState>
    );
  }
  return (
    <div className="architecture-grid">
      <div className="stack">
        <section className="panel">
          <div className="section-title">
            <h3>Workflow</h3>
            <CopyButton value={plan.mermaid} label="Copy Mermaid" />
          </div>
          <PlanFlow plan={plan} />
        </section>
        <section className="panel">
          <h3>Tool bindings</h3>
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Tool</th>
                <th scope="col">Mode</th>
                <th scope="col">Used by</th>
                <th scope="col">Phases</th>
                <th scope="col">Timeout</th>
              </tr>
            </thead>
            <tbody>
              {plan.tools.map(tool => (
                <tr key={tool.name}>
                  <td>
                    <code>{tool.name}</code>
                    <span className="cell-detail">{tool.description}</span>
                  </td>
                  <td>
                    <ModeBadge mode={tool.mode} approval={tool.approval_required} />
                  </td>
                  <td>{tool.used_by.join(', ')}</td>
                  <td>{tool.phases.join(', ')}</td>
                  <td>{tool.timeout_seconds} s</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>
      <div className="stack">
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
                  <span>{finding.detail}</span>
                  <span className="risk-mitigation">{finding.mitigation}</span>
                </div>
                <span className={`risk-status is-${finding.status}`}>{finding.status}</span>
              </li>
            ))}
          </ul>
        </section>
        <section className="panel">
          <h3>Components</h3>
          <dl className="components">
            {plan.components.map(component => (
              <div key={component.id}>
                <dt>
                  {component.title}
                  <span>{component.technology}</span>
                </dt>
                <dd>{component.detail}</dd>
              </div>
            ))}
          </dl>
        </section>
      </div>
    </div>
  );
}
