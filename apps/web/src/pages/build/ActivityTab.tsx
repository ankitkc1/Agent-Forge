import { useEffect, useRef } from 'react';
import { EmptyState } from '@/components/Feedback';
import type { Build } from '@/types';

function time(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export function ActivityTab({ build, live }: { build: Build; live: boolean }) {
  const list = useRef<HTMLOListElement>(null);
  const pinned = useRef(true);
  const count = build.events.length;

  useEffect(() => {
    const element = list.current;
    if (element && live && pinned.current) element.scrollTop = element.scrollHeight;
  }, [count, live]);

  if (count === 0) {
    return <EmptyState icon="list" title="No activity yet">Events appear as soon as a worker picks up the build.</EmptyState>;
  }
  return (
    <section className="panel">
      <ol
        ref={list}
        className="log"
        aria-live={live ? 'polite' : 'off'}
        aria-label="Build events"
        tabIndex={0}
        onScroll={event => {
          const element = event.currentTarget;
          pinned.current = element.scrollHeight - element.scrollTop - element.clientHeight < 40;
        }}
      >
        {build.events.map(event => (
          <li key={event.id} className={`log-line level-${event.level}`}>
            <time dateTime={event.created_at}>{time(event.created_at)}</time>
            <span className="log-stage">{event.stage ?? 'build'}</span>
            <span className="log-message">{event.message}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
