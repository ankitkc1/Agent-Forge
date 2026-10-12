import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { storeApiKey } from '@/lib/storage';
import { api, ApiError } from './client';

function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } });
}

function lastCall(mock: ReturnType<typeof vi.fn>): { url: string; init: RequestInit } {
  const call = mock.mock.calls.at(-1) as [string, RequestInit];
  return { url: call[0], init: call[1] };
}

function sentBody(init: RequestInit): unknown {
  return JSON.parse(typeof init.body === 'string' ? init.body : '{}');
}

const storage = new Map<string, string>();
const fakeStorage = {
  getItem: (key: string) => storage.get(key) ?? null,
  setItem: (key: string, value: string) => void storage.set(key, value),
  removeItem: (key: string) => void storage.delete(key),
};

beforeEach(() => {
  storage.clear();
  vi.stubGlobal('window', { sessionStorage: fakeStorage, localStorage: fakeStorage });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('api client', () => {
  it('sends the requirement and compiler engine only to the compile endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ spec: {}, spec_hash: 'a'.repeat(64), warnings: [] }));
    vi.stubGlobal('fetch', fetchMock);
    await api.compile('Build a governed support agent with human approval.', 'heuristic');
    const { url, init } = lastCall(fetchMock);
    expect(url).toBe('/api/v1/specs/compile');
    expect(init.method).toBe('POST');
    expect(sentBody(init)).toEqual({ requirement: 'Build a governed support agent with human approval.', options: { engine: 'heuristic' } });
  });

  it('binds builds to an idempotency key', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ id: 'b1' }, 202));
    vi.stubGlobal('fetch', fetchMock);
    await api.createBuild({ version: '1.0' } as never, 'f'.repeat(64), 'key-1');
    const { init } = lastCall(fetchMock);
    expect((init.headers as Record<string, string>)['Idempotency-Key']).toBe('key-1');
    expect(sentBody(init)).toEqual({ spec: { version: '1.0' }, spec_hash: 'f'.repeat(64) });
  });

  it('adds the stored API key as a bearer token', async () => {
    storeApiKey('secret-key');
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ items: [], next_cursor: null }));
    vi.stubGlobal('fetch', fetchMock);
    await api.listBuilds({ status: 'failed', agent: 'triage', cursor: 'abc' });
    const { url, init } = lastCall(fetchMock);
    expect(url).toBe('/api/v1/builds?limit=20&status=failed&agent=triage&cursor=abc');
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer secret-key');
  });

  it('encodes file paths segment by segment', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ path: 'x', content: '' }));
    vi.stubGlobal('fetch', fetchMock);
    await api.getFile('b1', 'src/agent/my file#1.py');
    expect(lastCall(fetchMock).url).toBe('/api/v1/builds/b1/files/src/agent/my%20file%231.py');
  });

  it('accepts empty 204 responses', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    await expect(api.deleteBuild('b1')).resolves.toBeUndefined();
  });

  it('surfaces string and validation error details', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ detail: 'AgentSpec hash mismatch' }, 409, { 'X-Request-ID': 'req-9' })));
    await expect(api.getBuild('unknown')).rejects.toMatchObject({ name: 'ApiError', status: 409, message: 'AgentSpec hash mismatch', requestId: 'req-9' });

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ detail: [{ loc: ['body', 'requirement'], msg: 'String should have at least 24 characters' }] }, 422)));
    await expect(api.compile('too short')).rejects.toThrow('requirement: String should have at least 24 characters');
  });

  it('explains authentication and network failures', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 401 })));
    const error = await api.system().catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).unauthorized).toBe(true);
    expect((error as ApiError).message).toMatch(/API key/);

    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    await expect(api.system()).rejects.toMatchObject({ status: 0, message: expect.stringMatching(/unreachable/) as unknown });
  });
});
