import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError } from './client';

afterEach(() => vi.restoreAllMocks());

describe('API client', () => {
  it('submits requirements only to the compiler endpoint', async () => {
    const response = {
      spec: { version: '1.0' },
      spec_hash: 'a'.repeat(64),
      warnings: [],
    };
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify(response), { status: 200, headers: { 'Content-Type': 'application/json' } }),
    );

    await api.compile('Build a governed support agent with human approval.');

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/v1/specs/compile');
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual({
      requirement: 'Build a governed support agent with human approval.',
    });
  });

  it('surfaces typed API errors', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ detail: 'AgentSpec hash mismatch' }), {
        status: 409,
        headers: { 'Content-Type': 'application/json' },
      }),
    );

    await expect(api.getBuild('unknown')).rejects.toMatchObject({
      name: 'ApiError',
      status: 409,
      message: 'AgentSpec hash mismatch',
    } satisfies Partial<ApiError>);
  });
});

