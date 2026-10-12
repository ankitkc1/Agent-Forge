import { useMutation, useQuery } from '@tanstack/react-query';
import { api } from '@/api/client';
import type { AgentSpec } from '@/types';

const terminalStatuses = new Set(['succeeded', 'failed', 'cancelled']);

export function useCompileSpec() {
  return useMutation({ mutationFn: (requirement: string) => api.compile(requirement) });
}

export function useCreateBuild() {
  return useMutation({
    mutationFn: ({ spec, specHash }: { spec: AgentSpec; specHash: string }) => api.createBuild(spec, specHash),
  });
}

export function useBuild(buildId: string | null) {
  return useQuery({
    queryKey: ['build', buildId],
    queryFn: () => api.getBuild(buildId!),
    enabled: Boolean(buildId),
    refetchInterval: query => {
      const status = query.state.data?.status;
      return status && terminalStatuses.has(status) ? false : 750;
    },
    retry: 2,
  });
}

