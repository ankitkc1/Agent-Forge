import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, type BuildFilters } from '@/api/client';
import type { AgentSpec, Build, BuildStatus, CompileEngine } from '@/types';

export const keys = {
  system: ['system'] as const,
  templates: ['templates'] as const,
  builds: (filters: Omit<BuildFilters, 'cursor'>) => ['builds', filters] as const,
  build: (id: string) => ['build', id] as const,
  report: (id: string) => ['build', id, 'report'] as const,
  files: (id: string) => ['build', id, 'files'] as const,
  file: (id: string, path: string) => ['build', id, 'file', path] as const,
};

export function useSystem() {
  return useQuery({ queryKey: keys.system, queryFn: api.system, staleTime: 60_000, retry: 1 });
}

export function useTemplates() {
  return useQuery({ queryKey: keys.templates, queryFn: api.templates, staleTime: Infinity });
}

export function useBuildList(filters: { status?: BuildStatus; agent?: string }) {
  return useInfiniteQuery({
    queryKey: keys.builds(filters),
    queryFn: ({ pageParam }) => api.listBuilds({ ...filters, cursor: pageParam, limit: 20 }),
    initialPageParam: null as string | null,
    getNextPageParam: page => page.next_cursor,
    refetchInterval: query => {
      const active = query.state.data?.pages.some(page => page.items.some(item => item.status === 'queued' || item.status === 'running'));
      return active ? 3000 : false;
    },
  });
}

export function useReport(id: string, version: string) {
  // ``version`` changes whenever a stage finishes, so the report refreshes as evidence arrives.
  return useQuery({ queryKey: [...keys.report(id), version], queryFn: () => api.getReport(id), placeholderData: previous => previous });
}

export function useFiles(id: string, enabled: boolean) {
  return useQuery({ queryKey: keys.files(id), queryFn: () => api.listFiles(id), enabled, staleTime: Infinity });
}

export function useFile(id: string, path: string | null) {
  return useQuery({
    queryKey: keys.file(id, path ?? ''),
    queryFn: () => api.getFile(id, path!),
    enabled: Boolean(path),
    staleTime: Infinity,
    retry: false,
  });
}

export function useCompile() {
  return useMutation({ mutationFn: ({ requirement, engine }: { requirement: string; engine: CompileEngine }) => api.compile(requirement, engine) });
}

export function useCreateBuild() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ spec, specHash, idempotencyKey }: { spec: AgentSpec; specHash: string; idempotencyKey: string }) =>
      api.createBuild(spec, specHash, idempotencyKey),
    onSuccess: build => {
      client.setQueryData(keys.build(build.id), build);
      void client.invalidateQueries({ queryKey: ['builds'] });
    },
  });
}

export function useBuildActions(id: string) {
  const client = useQueryClient();
  const settle = (build?: Build) => {
    if (build) client.setQueryData(keys.build(build.id), build);
    void client.invalidateQueries({ queryKey: ['builds'] });
  };
  return {
    cancel: useMutation({ mutationFn: () => api.cancelBuild(id), onSuccess: settle }),
    retry: useMutation({ mutationFn: () => api.retryBuild(id), onSuccess: settle }),
    remove: useMutation({
      mutationFn: () => api.deleteBuild(id),
      onSuccess: () => {
        client.removeQueries({ queryKey: keys.build(id) });
        void client.invalidateQueries({ queryKey: ['builds'] });
      },
    }),
  };
}
