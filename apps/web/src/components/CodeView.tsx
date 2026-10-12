import { useMemo } from 'react';

/** Read-only source view with line numbers. Content is rendered as text, never as HTML. */
export function CodeView({ content, label, maxLines = 4000 }: { content: string; label: string; maxLines?: number }) {
  const lines = useMemo(() => {
    const all = content.replace(/\n$/, '').split('\n');
    return { shown: all.slice(0, maxLines), hidden: Math.max(all.length - maxLines, 0) };
  }, [content, maxLines]);
  const gutter = String(lines.shown.length).length;
  return (
    <div className="code" role="region" aria-label={label} tabIndex={0}>
      <pre>
        {lines.shown.map((line, index) => (
          <span className="code-line" key={index}>
            <span className="code-number" style={{ width: `${gutter + 1}ch` }} aria-hidden="true">
              {index + 1}
            </span>
            <span className="code-text">{line || ' '}</span>
          </span>
        ))}
      </pre>
      {lines.hidden > 0 ? <p className="code-more">{lines.hidden} more lines not shown.</p> : null}
    </div>
  );
}
