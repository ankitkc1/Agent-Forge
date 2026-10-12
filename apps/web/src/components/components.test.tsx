// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PlanFlow, TopologyChecks } from '@/components/PlanFlow';
import { StageRail } from '@/components/StageRail';
import { BuildsPage } from '@/pages/BuildsPage';
import { OverviewTab } from '@/pages/build/OverviewTab';
import { TestsTab } from '@/pages/build/TestsTab';
import { buildFixture, reportFixture } from '@/test/fixtures';
import type { BuildPage } from '@/types';

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function withClient(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{node}</QueryClientProvider>;
}

describe('PlanFlow', () => {
  const plan = reportFixture.plan!;

  it('draws every workflow node in order with the approval gate across the flow', () => {
    render(<PlanFlow plan={plan} />);
    const items = within(screen.getByRole('list', { name: /workflow/ })).getAllByRole('listitem', { name: undefined });
    const titles = screen.getAllByText(/./, { selector: '.flow-head strong, .gate-band strong' }).map(node => node.textContent);
    expect(titles[0]).toBe('Input guard');
    expect(titles.at(-1)).toBe('Finalize & audit');
    expect(items.length).toBeGreaterThanOrEqual(plan.nodes.length);
    expect(screen.getByText(/Nothing below this line runs until a reviewer approves/)).toBeTruthy();
    expect(screen.getByText('Side effects')).toBeTruthy();
    expect(screen.getAllByText(/If blocked/).length).toBe(2);
    expect(screen.getByText(/If rejected/)).toBeTruthy();
  });

  it('marks approval-gated tools', () => {
    render(<PlanFlow plan={plan} />);
    const execute = screen.getAllByText('send_tenant_email')[0]!.closest('li')!;
    expect(within(execute).getByTitle('Requires human approval')).toBeTruthy();
  });

  it('lists verified properties', () => {
    render(<TopologyChecks plan={plan} />);
    expect(screen.getByText('Human approval dominates every side-effecting node')).toBeTruthy();
  });
});

describe('StageRail', () => {
  it('shows each stage with its evidence summary', () => {
    const stages = buildFixture.stages.map((stage, index) => (index === 4 ? { ...stage, attempts: 2 } : stage));
    render(<StageRail stages={stages} now={Date.parse(buildFixture.updated_at)} />);
    const rail = screen.getByRole('list', { name: 'Pipeline stages' });
    expect(within(rail).getAllByRole('listitem')).toHaveLength(10);
    expect(screen.getByText('152 passed, 0 skipped, coverage 90.8%')).toBeTruthy();
    expect(screen.getByText(/2 attempts/)).toBeTruthy();
  });
});

describe('build tabs', () => {
  it('compares measured quality with the evaluation targets', () => {
    render(withClient(<OverviewTab build={buildFixture} report={reportFixture} />));
    expect(screen.getByRole('button', { name: /Download source/ })).toBeTruthy();
    expect(screen.getByText('152/152')).toBeTruthy();
    expect(screen.getAllByText(/Target 90/).length).toBeGreaterThan(0);
    expect(screen.getByText('property-maintenance-triage-agent/')).toBeTruthy();
  });

  it('filters test cases to failures', () => {
    render(<TestsTab build={buildFixture} report={reportFixture} />);
    fireEvent.click(screen.getByRole('button', { name: 'Failing' }));
    expect(screen.getByText('test_partial_approval')).toBeTruthy();
    expect(screen.getByText(/expected 1 executed action/)).toBeTruthy();
    expect(screen.queryByText('tests/unit/test_config.py')).toBeNull();
  });
});

describe('BuildsPage', () => {
  it('lists builds with their evidence', async () => {
    const page: BuildPage = { items: [buildFixture], next_cursor: null };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(page), { status: 200, headers: { 'Content-Type': 'application/json' } })));
    render(withClient(<BuildsPage />));
    expect(await screen.findByText('Property maintenance triage')).toBeTruthy();
    expect(screen.getByText('152/152 tests')).toBeTruthy();
    expect(screen.getByRole('button', { name: /Download property-maintenance-triage-agent source/ })).toBeTruthy();
  });

  it('invites a first build when there are none', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [], next_cursor: null }), { status: 200, headers: { 'Content-Type': 'application/json' } })));
    render(withClient(<BuildsPage />));
    expect(await screen.findByText('No builds yet')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Compile a requirement' }).getAttribute('href')).toBe('/');
  });
});
