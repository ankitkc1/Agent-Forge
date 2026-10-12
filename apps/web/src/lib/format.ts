const percentFormatter = new Intl.NumberFormat(undefined, { style: 'percent', maximumFractionDigits: 1 });
const integerFormatter = new Intl.NumberFormat();
const relativeFormatter = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });

/** 0.9085 -> "90.9%" */
export function formatPercent(ratio: number | null | undefined): string {
  if (ratio === null || ratio === undefined || Number.isNaN(ratio)) return '—';
  return percentFormatter.format(ratio);
}

export function formatInteger(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : integerFormatter.format(value);
}

/** Seconds -> "420 ms", "18.4 s", "2 min 05 s", "1 h 02 min". */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return '—';
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`;
  if (seconds < 60) return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)} s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ${String(Math.round(seconds % 60)).padStart(2, '0')} s`;
  return `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, '0')} min`;
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return '—';
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KB', 'MB', 'GB'];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} ${units[unit]}`;
}

export function shortHash(hash: string | null | undefined, length = 12): string {
  return hash ? hash.slice(0, length) : '—';
}

export function shortId(id: string): string {
  return id.slice(0, 8);
}

/** "property_maintenance_triage" -> "Property maintenance triage" */
export function humanize(identifier: string): string {
  const words = identifier.replaceAll('_', ' ').trim();
  return words ? words[0]!.toUpperCase() + words.slice(1) : identifier;
}

export function repositoryName(agentName: string): string {
  return `${agentName.replaceAll('_', '-')}-agent`;
}

/** Matches the API's Content-Disposition name, so commands shown in the UI fit the download. */
export function artifactFileName(agentName: string, buildId: string): string {
  return `${repositoryName(agentName)}-${buildId.slice(0, 8)}.zip`;
}

export function relativeTime(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return '—';
  const timestamp = Date.parse(iso);
  if (Number.isNaN(timestamp)) return '—';
  const seconds = Math.round((timestamp - now) / 1000);
  const abs = Math.abs(seconds);
  if (abs < 45) return relativeFormatter.format(0, 'second');
  if (abs < 3600) return relativeFormatter.format(Math.round(seconds / 60), 'minute');
  if (abs < 86400) return relativeFormatter.format(Math.round(seconds / 3600), 'hour');
  return relativeFormatter.format(Math.round(seconds / 86400), 'day');
}

export function absoluteTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString();
}

export function pluralize(count: number, singular: string, plural = `${singular}s`): string {
  return `${formatInteger(count)} ${count === 1 ? singular : plural}`;
}
