import { EmptyState } from '@/components/Feedback';
import { Icon } from '@/components/Icon';
import { Link } from '@/components/Link';
import { SeverityBadge, StateBadge } from '@/components/Status';
import { buildPath } from '@/router';
import type { Build, BuildReport, Severity } from '@/types';

const ORDER: Severity[] = ['critical', 'high', 'medium', 'low', 'info'];

export function SecurityTab({ build, report }: { build: Build; report: Partial<BuildReport> | undefined }) {
  const security = report?.security;
  if (!security) {
    return (
      <EmptyState icon="shield" title="Security validation has not run">
        After the gates pass, every file is scanned for secrets, dangerous calls, unpinned dependencies and container misconfiguration, and bandit runs in the sandbox.
      </EmptyState>
    );
  }
  return (
    <div className="stack">
      <section className="summary-strip" aria-label="Findings by severity">
        <div>
          <StateBadge status={security.status} />
          <span>{security.files_scanned} files scanned</span>
        </div>
        {ORDER.map(severity => (
          <div key={severity} className={security.summary[severity] && (severity === 'critical' || severity === 'high') ? 'is-bad' : ''}>
            <strong>{security.summary[severity] ?? 0}</strong>
            <span>{severity}</span>
          </div>
        ))}
      </section>

      <section className="panel">
        <h3>Findings</h3>
        {security.findings.length === 0 ? (
          <p className="clean">
            <Icon name="check" /> No findings. Critical and high findings would have blocked packaging.
          </p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Severity</th>
                <th scope="col">Finding</th>
                <th scope="col">Location</th>
                <th scope="col">Source</th>
              </tr>
            </thead>
            <tbody>
              {security.findings.map((finding, index) => (
                <tr key={`${finding.rule_id}-${finding.path ?? ''}-${finding.line ?? index}`}>
                  <td>
                    <SeverityBadge severity={finding.severity} />
                    {finding.blocking ? <span className="cell-detail">blocks packaging</span> : null}
                  </td>
                  <td>
                    <strong>{finding.title}</strong>
                    <span className="cell-detail">
                      <code>{finding.rule_id}</code> {finding.detail}
                    </span>
                  </td>
                  <td>
                    {finding.path ? (
                      build.artifact_ready ? (
                        <Link to={buildPath(build.id, 'files', finding.path)}>
                          <code>
                            {finding.path}
                            {finding.line ? `:${finding.line}` : ''}
                          </code>
                        </Link>
                      ) : (
                        <code>
                          {finding.path}
                          {finding.line ? `:${finding.line}` : ''}
                        </code>
                      )
                    ) : (
                      '—'
                    )}
                  </td>
                  <td>{finding.source}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="panel">
        <h3>Checks performed</h3>
        <ul className="checklist">
          {security.checks.map(check => (
            <li key={check} className="is-pass">
              <Icon name="check" />
              <div>
                <strong>{check}</strong>
              </div>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
