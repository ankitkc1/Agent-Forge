import { useMemo, useState } from 'react';
import { EmptyState } from '@/components/Feedback';
import { Icon, type IconName } from '@/components/Icon';
import { formatDuration, formatPercent } from '@/lib/format';
import { groupByFile } from '@/lib/report';
import { CommandOutput } from '@/pages/build/GateDetails';
import type { Build, BuildReport, TestCaseResult } from '@/types';

type Filter = 'all' | 'problems' | 'skipped';

const OUTCOME_ICON: Record<TestCaseResult['outcome'], IconName> = { passed: 'check', failed: 'x', error: 'alert', skipped: 'arrow' };

export function TestsTab({ build, report }: { build: Build; report: Partial<BuildReport> | undefined }) {
  const gate = report?.gates?.tests;
  const [filter, setFilter] = useState<Filter>('all');
  const [query, setQuery] = useState('');
  const [allCoverage, setAllCoverage] = useState(false);

  const groups = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const cases = (gate?.test_cases ?? []).filter(testCase => {
      if (filter === 'problems' && testCase.outcome !== 'failed' && testCase.outcome !== 'error') return false;
      if (filter === 'skipped' && testCase.outcome !== 'skipped') return false;
      return !needle || testCase.id.toLowerCase().includes(needle);
    });
    return groupByFile(cases);
  }, [gate?.test_cases, filter, query]);

  if (!gate?.tests) {
    return (
      <EmptyState icon="beaker" title={build.status === 'running' || build.status === 'queued' ? 'Tests have not run yet' : 'No test evidence'}>
        The generated repository's pytest suite runs in the sandbox; results are parsed from its JUnit report.
      </EmptyState>
    );
  }
  const tests = gate.tests;
  const coverage = gate.coverage;
  const coverageFiles = [...(coverage?.files ?? [])].sort((a, b) => a.percent - b.percent || a.path.localeCompare(b.path));
  const fullyCovered = coverageFiles.filter(file => file.percent >= 100).length;
  const shownCoverage = allCoverage ? coverageFiles : coverageFiles.filter(file => file.percent < 100);

  return (
    <div className="stack">
      <section className="summary-strip" aria-label="Test summary">
        <div>
          <strong>{tests.passed}</strong>
          <span>passed</span>
        </div>
        <div className={tests.failed + tests.errors ? 'is-bad' : ''}>
          <strong>{tests.failed + tests.errors}</strong>
          <span>failed</span>
        </div>
        <div>
          <strong>{tests.skipped}</strong>
          <span>skipped</span>
        </div>
        <div>
          <strong>{formatDuration(tests.duration_seconds)}</strong>
          <span>pytest time</span>
        </div>
        <div>
          <strong>{coverage ? formatPercent(coverage.percent / 100) : '—'}</strong>
          <span>line coverage</span>
        </div>
      </section>

      <section className="panel">
        <div className="section-title">
          <h3>Test cases</h3>
          <div className="toolbar toolbar-tight">
            <div className="segmented" role="group" aria-label="Filter test cases">
              {(['all', 'problems', 'skipped'] as const).map(value => (
                <button key={value} type="button" className={filter === value ? 'is-selected' : ''} aria-pressed={filter === value} onClick={() => setFilter(value)}>
                  {value === 'all' ? 'All' : value === 'problems' ? 'Failing' : 'Skipped'}
                </button>
              ))}
            </div>
            <label className="search">
              <Icon name="search" />
              <span className="sr-only">Filter tests by name</span>
              <input type="search" placeholder="Test name" value={query} onChange={event => setQuery(event.target.value)} />
            </label>
          </div>
        </div>
        {groups.length === 0 ? (
          <p className="muted">No test cases match.</p>
        ) : (
          <div className="case-groups">
            {groups.map(group => (
              <details key={group.file} className="case-group" open={filter !== 'all' || groups.length <= 3 || group.cases.some(item => item.outcome === 'failed' || item.outcome === 'error')}>
                <summary>
                  <code>{group.file}</code>
                  <span>
                    {group.cases.filter(item => item.outcome === 'passed').length}/{group.cases.length}
                  </span>
                </summary>
                <ul className="cases">
                  {group.cases.map(testCase => (
                    <li key={testCase.id} className={`case is-${testCase.outcome}`}>
                      <Icon name={OUTCOME_ICON[testCase.outcome]} />
                      <span className="case-name">{testCase.id.split('::').slice(1).join('::') || testCase.id}</span>
                      <span className="case-time">{formatDuration(testCase.duration_seconds)}</span>
                      {testCase.message && testCase.outcome !== 'passed' ? <pre className="case-message">{testCase.message}</pre> : null}
                    </li>
                  ))}
                </ul>
              </details>
            ))}
          </div>
        )}
      </section>

      {coverageFiles.length ? (
        <section className="panel">
          <h3>Coverage by file</h3>
          <p className="help">Least covered first. Offline tests cannot reach production-only paths such as Postgres or HTTP providers.</p>
          <ul className="bars" aria-label="Coverage by file">
            {shownCoverage.map(file => (
              <li key={file.path}>
                <code>{file.path}</code>
                <span className="bar">
                  <span style={{ width: `${file.percent}%` }} />
                </span>
                <span className="bar-value">{formatPercent(file.percent / 100)}</span>
              </li>
            ))}
          </ul>
          {fullyCovered ? (
            <button type="button" className="button button-quiet button-small coverage-toggle" onClick={() => setAllCoverage(value => !value)}>
              {allCoverage ? 'Hide fully covered files' : `Show ${fullyCovered} fully covered ${fullyCovered === 1 ? 'file' : 'files'}`}
            </button>
          ) : null}
        </section>
      ) : null}

      {gate.commands.length ? (
        <section className="panel">
          <h3>Sandbox command</h3>
          {gate.commands.map((command, index) => (
            <CommandOutput key={`${command.command}-${index}`} command={command} />
          ))}
        </section>
      ) : null}
    </div>
  );
}
