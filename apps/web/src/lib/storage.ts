// Browser storage that never throws: private windows, blocked storage and SSR all degrade to
// "nothing stored" instead of breaking the workbench.

type Area = 'session' | 'local';

function area(kind: Area): Storage | null {
  try {
    return kind === 'session' ? window.sessionStorage : window.localStorage;
  } catch {
    return null;
  }
}

export function readItem(key: string, kind: Area = 'local'): string | null {
  try {
    return area(kind)?.getItem(key) ?? null;
  } catch {
    return null;
  }
}

export function writeItem(key: string, value: string | null, kind: Area = 'local'): void {
  try {
    const storage = area(kind);
    if (!storage) return;
    if (value === null) storage.removeItem(key);
    else storage.setItem(key, value);
  } catch {
    // Storage is a convenience only.
  }
}

const API_KEY = 'agentforge.api-key';

/** The API key lives in session storage unless the user chose to remember it on this device. */
export function readApiKey(): string | null {
  return readItem(API_KEY, 'session') ?? readItem(API_KEY, 'local');
}

export function storeApiKey(key: string | null, remember = false): void {
  writeItem(API_KEY, null, 'session');
  writeItem(API_KEY, null, 'local');
  if (key) writeItem(API_KEY, key, remember ? 'local' : 'session');
}
