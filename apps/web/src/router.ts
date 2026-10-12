// A small History API router: the workbench has five screens, which does not justify a
// routing dependency. Paths are bookmarkable and the server falls back to index.html.
import { useSyncExternalStore } from 'react';

export const BUILD_TABS = ['overview', 'architecture', 'tests', 'evaluation', 'security', 'files', 'provenance', 'activity'] as const;
export type BuildTab = (typeof BUILD_TABS)[number];

export type Route =
  | { name: 'compose'; template: string | null }
  | { name: 'builds' }
  | { name: 'build'; id: string; tab: BuildTab; file: string | null }
  | { name: 'templates' }
  | { name: 'system' }
  | { name: 'not-found'; path: string };

const BUILD_ID = /^[0-9a-f-]{8,64}$/i;

export function parseRoute(pathname: string, search = ''): Route {
  const params = new URLSearchParams(search);
  const path = pathname.replace(/\/+$/, '') || '/';
  if (path === '/' || path === '/new') return { name: 'compose', template: params.get('template') };
  if (path === '/builds') return { name: 'builds' };
  if (path === '/templates') return { name: 'templates' };
  if (path === '/system') return { name: 'system' };
  const build = /^\/builds\/([^/]+)$/.exec(path);
  if (build?.[1] && BUILD_ID.test(build[1])) {
    const tab = params.get('tab');
    return {
      name: 'build',
      id: build[1].toLowerCase(),
      tab: (BUILD_TABS as readonly string[]).includes(tab ?? '') ? (tab as BuildTab) : 'overview',
      file: params.get('file'),
    };
  }
  return { name: 'not-found', path };
}

export function buildPath(id: string, tab: BuildTab = 'overview', file?: string | null): string {
  const query = new URLSearchParams();
  if (tab !== 'overview') query.set('tab', tab);
  if (file) query.set('file', file);
  const suffix = query.toString();
  return `/builds/${id}${suffix ? `?${suffix}` : ''}`;
}

const NAVIGATION_EVENT = 'agentforge:navigate';

export function navigate(to: string, { replace = false } = {}): void {
  if (to === `${window.location.pathname}${window.location.search}`) return;
  if (replace) window.history.replaceState(null, '', to);
  else window.history.pushState(null, '', to);
  window.dispatchEvent(new Event(NAVIGATION_EVENT));
}

function subscribe(callback: () => void): () => void {
  window.addEventListener('popstate', callback);
  window.addEventListener(NAVIGATION_EVENT, callback);
  return () => {
    window.removeEventListener('popstate', callback);
    window.removeEventListener(NAVIGATION_EVENT, callback);
  };
}

function snapshot(): string {
  return `${window.location.pathname}${window.location.search}`;
}

export function useLocationKey(): string {
  return useSyncExternalStore(subscribe, snapshot, () => '/');
}

export function useRoute(): Route {
  const key = useLocationKey();
  const index = key.indexOf('?');
  return parseRoute(index === -1 ? key : key.slice(0, index), index === -1 ? '' : key.slice(index));
}
