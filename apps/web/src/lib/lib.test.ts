import { describe, expect, it } from 'vitest';
import { mergeEvent } from '@/hooks/useBuildLive';
import type { Build, FileEntry } from '@/types';
import { formatBytes, formatDuration, formatPercent, humanize, relativeTime, repositoryName } from './format';
import { ancestors, buildTree, groupByFile } from './report';

describe('format', () => {
  it('formats ratios, durations and sizes', () => {
    expect(formatPercent(0.9085)).toMatch(/90\.9\s?%/);
    expect(formatPercent(null)).toBe('—');
    expect(formatDuration(0.42)).toBe('420 ms');
    expect(formatDuration(18.43)).toBe('18 s');
    expect(formatDuration(4.25)).toBe('4.3 s');
    expect(formatDuration(125)).toBe('2 min 05 s');
    expect(formatDuration(3720)).toBe('1 h 02 min');
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(316_043)).toBe('309 KB');
    expect(formatBytes(5 * 1024 * 1024)).toBe('5.0 MB');
  });

  it('names agents and repositories', () => {
    expect(humanize('property_maintenance_triage')).toBe('Property maintenance triage');
    expect(repositoryName('property_maintenance_triage')).toBe('property-maintenance-triage-agent');
  });

  it('describes time relative to a clock', () => {
    const now = Date.parse('2026-10-12T10:00:00Z');
    expect(relativeTime('2026-10-12T09:58:00Z', now)).toMatch(/2 minutes ago/);
    expect(relativeTime('2026-10-12T09:59:50Z', now)).toMatch(/now/);
    expect(relativeTime(null, now)).toBe('—');
  });
});

describe('report helpers', () => {
  it('groups test cases by file', () => {
    const groups = groupByFile([
      { id: 'tests/unit/test_a.py::test_one', outcome: 'passed', duration_seconds: 0, message: null },
      { id: 'tests/unit/test_b.py::test_two', outcome: 'failed', duration_seconds: 0, message: 'boom' },
      { id: 'tests/unit/test_a.py::test_three', outcome: 'skipped', duration_seconds: 0, message: null },
    ]);
    expect(groups.map(group => [group.file, group.cases.length])).toEqual([
      ['tests/unit/test_a.py', 2],
      ['tests/unit/test_b.py', 1],
    ]);
  });

  it('builds a folders-first file tree', () => {
    const entry = (path: string): FileEntry => ({ path, size: 1, sha256: null, evidence: path.startsWith('.agentforge/') });
    const tree = buildTree([entry('README.md'), entry('src/agent/graph.py'), entry('src/api/main.py'), entry('Dockerfile'), entry('.agentforge/MANIFEST.sha256')]);
    expect(tree.children.map(child => child.name)).toEqual(['.agentforge', 'src', 'Dockerfile', 'README.md']);
    expect(tree.children[1]?.children.map(child => child.path)).toEqual(['src/agent', 'src/api']);
    expect(ancestors('src/agent/graph.py')).toEqual(['src', 'src/agent']);
  });

  it('merges streamed events without duplicates', () => {
    const build = { events: [{ id: 1, created_at: '', level: 'info', stage: null, message: 'queued' }], logs: ['queued'] } as unknown as Build;
    const next = mergeEvent(build, { id: 2, created_at: '', level: 'info', stage: 'tests', message: 'tests passed' });
    expect(next?.logs).toEqual(['queued', 'tests passed']);
    expect(mergeEvent(next, { id: 2, created_at: '', level: 'info', stage: 'tests', message: 'tests passed' })).toBe(next);
  });
});
