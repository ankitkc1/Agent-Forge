import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { api, ApiError, authHeaders } from '@/api/client';
import { readEventStream } from '@/api/sse';
import { keys } from '@/hooks/queries';
import { TERMINAL_STATUSES, type Build, type BuildEvent } from '@/types';

export type LiveMode = 'connecting' | 'live' | 'polling' | 'idle';

const MAX_EVENTS = 400;
const POLL_MS = 2000;

export function mergeEvent(build: Build | undefined, event: BuildEvent): Build | undefined {
  if (!build || build.events.some(existing => existing.id === event.id)) return build;
  const events = [...build.events, event].slice(-MAX_EVENTS);
  return { ...build, events, logs: events.map(item => item.message) };
}

const wait = (ms: number, signal: AbortSignal) =>
  new Promise<void>(resolve => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener('abort', () => {
      clearTimeout(timer);
      resolve();
    });
  });

/**
 * Build state with live updates: server-sent events while the build runs, falling back to
 * polling when the stream is unavailable (for example behind a buffering proxy).
 */
export function useBuildLive(id: string) {
  const client = useQueryClient();
  const [streamMode, setStreamMode] = useState<Exclude<LiveMode, 'idle'>>('connecting');
  const modeRef = useRef<LiveMode>('connecting');

  const query = useQuery({
    queryKey: keys.build(id),
    queryFn: () => api.getBuild(id),
    refetchInterval: current => {
      const status = current.state.data?.status;
      if (!status || TERMINAL_STATUSES.has(status)) return false;
      return modeRef.current === 'live' ? false : POLL_MS;
    },
    retry: (count, error) => !(error instanceof ApiError && (error.status === 404 || error.status === 401)) && count < 2,
  });

  const loaded = query.data !== undefined;
  const terminal = query.data ? TERMINAL_STATUSES.has(query.data.status) : false;

  useEffect(() => {
    if (!loaded || terminal) return;
    const controller = new AbortController();
    const { signal } = controller;

    const run = async () => {
      let failures = 0;
      while (!signal.aborted && failures < 3) {
        try {
          await readEventStream(api.streamUrl(id), {
            headers: authHeaders(),
            signal,
            onMessage: message => {
              failures = 0;
              setStreamMode('live');
              if (message.event === 'build') {
                client.setQueryData(keys.build(id), JSON.parse(message.data) as Build);
              } else if (message.event === 'log') {
                const event = JSON.parse(message.data) as BuildEvent;
                client.setQueryData<Build>(keys.build(id), current => mergeEvent(current, event));
              } else if (message.event === 'end') {
                void client.invalidateQueries({ queryKey: keys.build(id) });
              }
            },
          });
          const latest = client.getQueryData<Build>(keys.build(id));
          if (signal.aborted || (latest && TERMINAL_STATUSES.has(latest.status))) return;
        } catch {
          if (signal.aborted) return;
          failures += 1;
        }
        setStreamMode('connecting');
        await wait(1000 * Math.max(failures, 1), signal);
      }
      if (!signal.aborted) setStreamMode('polling');
    };
    void run();
    return () => controller.abort();
  }, [id, loaded, terminal, client]);

  const mode: LiveMode = !loaded || terminal ? 'idle' : streamMode;
  useEffect(() => {
    modeRef.current = mode;
  }, [mode]);

  return { ...query, mode };
}
