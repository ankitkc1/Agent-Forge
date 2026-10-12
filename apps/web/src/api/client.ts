import { readApiKey } from '@/lib/storage';
import type {
  AgentSpec,
  Build,
  BuildEvent,
  BuildPage,
  BuildReport,
  BuildStatus,
  CompileEngine,
  CompileResponse,
  FileContent,
  FileEntry,
  RequirementTemplate,
  SystemInfo,
  ValidateResponse,
} from '@/types';

export const API_BASE = ((import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '/api/v1').replace(/\/$/, '');

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly requestId?: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }

  get unauthorized(): boolean {
    return this.status === 401;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** FastAPI errors are ``{"detail": "..."}`` or a list of ``{"loc": [...], "msg": "..."}``. */
function describeError(body: unknown, status: number): string {
  const detail = isRecord(body) ? body.detail : undefined;
  if (typeof detail === 'string' && detail) return detail;
  if (Array.isArray(detail) && isRecord(detail[0]) && typeof detail[0].msg === 'string') {
    const loc = Array.isArray(detail[0].loc) ? detail[0].loc : [];
    const location = loc.filter(part => part !== 'body' && (typeof part === 'string' || typeof part === 'number')).join('.');
    return location ? `${location}: ${detail[0].msg}` : detail[0].msg;
  }
  if (status === 401) return 'An API key is required. Add one in Settings.';
  if (status === 429) return 'Too many builds are running. Try again in a moment.';
  if (status >= 500) return `The AgentForge API failed (HTTP ${status}).`;
  return `Request failed (HTTP ${status}).`;
}

export function authHeaders(): Record<string, string> {
  const key = readApiKey();
  return key ? { Authorization: `Bearer ${key}` } : {};
}

interface RequestOptions extends RequestInit {
  expect?: 'json' | 'none';
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { expect = 'json', headers, ...init } = options;
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        Accept: 'application/json',
        ...(init.body ? { 'Content-Type': 'application/json' } : {}),
        ...authHeaders(),
        ...(headers as Record<string, string> | undefined),
      },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError('The AgentForge API is unreachable. Check that the API service is running.', 0);
  }
  const requestId = response.headers.get('X-Request-ID') ?? undefined;
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => ({}));
    const bodyRequestId = isRecord(body) && typeof body.request_id === 'string' ? body.request_id : undefined;
    throw new ApiError(describeError(body, response.status), response.status, requestId ?? bodyRequestId);
  }
  if (expect === 'none' || response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function encodePath(path: string): string {
  return path.split('/').map(encodeURIComponent).join('/');
}

export interface BuildFilters {
  status?: BuildStatus;
  agent?: string;
  limit?: number;
  cursor?: string | null;
}

export const api = {
  system: () => request<SystemInfo>('/system'),
  templates: () => request<RequirementTemplate[]>('/specs/templates'),

  compile: (requirement: string, engine: CompileEngine = 'auto') =>
    request<CompileResponse>('/specs/compile', {
      method: 'POST',
      body: JSON.stringify({ requirement, options: { engine } }),
    }),

  validateDocument: (document: string, signal?: AbortSignal) =>
    request<ValidateResponse>('/specs/validate', { method: 'POST', body: JSON.stringify({ document }), signal }),

  validateSpec: (spec: AgentSpec, signal?: AbortSignal) =>
    request<ValidateResponse>('/specs/validate', { method: 'POST', body: JSON.stringify({ spec }), signal }),

  listBuilds: ({ status, agent, limit = 20, cursor }: BuildFilters = {}) => {
    const query = new URLSearchParams({ limit: String(limit) });
    if (status) query.set('status', status);
    if (agent) query.set('agent', agent);
    if (cursor) query.set('cursor', cursor);
    return request<BuildPage>(`/builds?${query.toString()}`);
  },

  getBuild: (id: string) => request<Build>(`/builds/${encodeURIComponent(id)}`),
  getReport: (id: string) => request<Partial<BuildReport>>(`/builds/${encodeURIComponent(id)}/report`),
  getEvents: (id: string, after = 0) => request<BuildEvent[]>(`/builds/${encodeURIComponent(id)}/events?after=${after}`),
  listFiles: (id: string) => request<FileEntry[]>(`/builds/${encodeURIComponent(id)}/files`),
  getFile: (id: string, path: string) => request<FileContent>(`/builds/${encodeURIComponent(id)}/files/${encodePath(path)}`),

  createBuild: (spec: AgentSpec, specHash: string, idempotencyKey?: string) =>
    request<Build>('/builds', {
      method: 'POST',
      body: JSON.stringify({ spec, spec_hash: specHash }),
      headers: idempotencyKey ? { 'Idempotency-Key': idempotencyKey } : undefined,
    }),

  cancelBuild: (id: string) => request<Build>(`/builds/${encodeURIComponent(id)}/cancel`, { method: 'POST' }),
  retryBuild: (id: string) => request<Build>(`/builds/${encodeURIComponent(id)}/retry`, { method: 'POST' }),
  deleteBuild: (id: string) => request<undefined>(`/builds/${encodeURIComponent(id)}`, { method: 'DELETE', expect: 'none' }),

  streamUrl: (id: string) => `${API_BASE}/builds/${encodeURIComponent(id)}/stream`,
  artifactUrl: (id: string) => `${API_BASE}/builds/${encodeURIComponent(id)}/artifact`,
  signingKeyUrl: () => `${API_BASE}/system/signing-key`,
};

function filenameFrom(disposition: string | null, fallback: string): string {
  const match = disposition?.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i);
  return match?.[1] ? decodeURIComponent(match[1]) : fallback;
}

/**
 * Download a build artifact. Without an API key the browser streams the file directly; with one,
 * the archive is fetched with the Authorization header and handed to the browser as a blob.
 */
export async function downloadArtifact(id: string, fallbackName: string): Promise<void> {
  const url = api.artifactUrl(id);
  const headers = authHeaders();
  const anchor = document.createElement('a');
  if (!headers.Authorization) {
    anchor.href = url;
    anchor.download = fallbackName;
    anchor.click();
    return;
  }
  const response = await fetch(url, { headers });
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => ({}));
    throw new ApiError(describeError(body, response.status), response.status);
  }
  const blobUrl = URL.createObjectURL(await response.blob());
  try {
    anchor.href = blobUrl;
    anchor.download = filenameFrom(response.headers.get('Content-Disposition'), fallbackName);
    anchor.click();
  } finally {
    setTimeout(() => URL.revokeObjectURL(blobUrl), 30_000);
  }
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return 'Something went wrong.';
}
