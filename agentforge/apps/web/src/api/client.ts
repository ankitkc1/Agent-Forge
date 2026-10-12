import { z } from 'zod';
import type { AgentSpec, Build, CompiledSpec } from '@/types';

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? '/api/v1';

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly requestId?: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

const errorSchema = z.object({
  detail: z.union([z.string(), z.array(z.unknown())]).optional(),
  request_id: z.string().optional(),
});

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });

  if (!response.ok) {
    const parsed = errorSchema.safeParse(await response.json().catch(() => ({})));
    const detail = parsed.success ? parsed.data.detail : undefined;
    const message = typeof detail === 'string' ? detail : `Request failed with status ${response.status}`;
    throw new ApiError(message, response.status, parsed.success ? parsed.data.request_id : undefined);
  }

  return response.json() as Promise<T>;
}

export const api = {
  compile(requirement: string): Promise<CompiledSpec> {
    return request('/specs/compile', {
      method: 'POST',
      body: JSON.stringify({ requirement }),
    });
  },

  createBuild(spec: AgentSpec, specHash: string): Promise<Build> {
    return request('/builds', {
      method: 'POST',
      body: JSON.stringify({ spec, spec_hash: specHash }),
    });
  },

  getBuild(buildId: string): Promise<Build> {
    return request(`/builds/${encodeURIComponent(buildId)}`);
  },

  artifactUrl(buildId: string): string {
    return `${API_BASE}/builds/${encodeURIComponent(buildId)}/artifact`;
  },
};

