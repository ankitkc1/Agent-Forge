import { useEffect, useRef, useState, type ReactNode } from 'react';
import { errorMessage } from '@/api/client';
import { Icon, type IconName } from '@/components/Icon';

export function Notice({
  tone = 'info',
  title,
  children,
  action,
}: {
  tone?: 'info' | 'warn' | 'bad' | 'good';
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  const icon: IconName = tone === 'bad' ? 'alert' : tone === 'warn' ? 'alert' : tone === 'good' ? 'check' : 'info';
  return (
    <div className={`notice notice-${tone}`} role={tone === 'bad' ? 'alert' : 'status'}>
      <Icon name={icon} />
      <div>
        <strong>{title}</strong>
        {children ? <div className="notice-body">{children}</div> : null}
      </div>
      {action}
    </div>
  );
}

export function ErrorNotice({ error, title = 'Request failed', onRetry }: { error: unknown; title?: string; onRetry?: () => void }) {
  return (
    <Notice
      tone="bad"
      title={title}
      action={
        onRetry ? (
          <button type="button" className="button button-quiet" onClick={onRetry}>
            <Icon name="refresh" />
            Try again
          </button>
        ) : undefined
      }
    >
      {errorMessage(error)}
    </Notice>
  );
}

export function EmptyState({ icon, title, children, action }: { icon: IconName; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <span className="empty-icon">
        <Icon name={icon} />
      </span>
      <h3>{title}</h3>
      {children ? <p>{children}</p> : null}
      {action}
    </div>
  );
}

export function Skeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div className="skeleton" aria-busy="true" aria-label="Loading">
      {Array.from({ length: lines }, (_, index) => (
        <span key={index} style={{ width: `${92 - index * 14}%` }} />
      ))}
    </div>
  );
}

export function CopyButton({ value, label = 'Copy', className = 'button button-quiet' }: { value: string; label?: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  };
  return (
    <button type="button" className={className} onClick={() => void copy()} aria-live="polite">
      <Icon name={copied ? 'check' : 'copy'} />
      {copied ? 'Copied' : label}
    </button>
  );
}

export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel,
  tone = 'bad',
  pending,
  onConfirm,
  onClose,
}: {
  open: boolean;
  title: string;
  children: ReactNode;
  confirmLabel: string;
  tone?: 'bad' | 'primary';
  pending?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);
  return (
    <dialog ref={ref} className="dialog" onClose={onClose} aria-labelledby="confirm-title">
      <h2 id="confirm-title">{title}</h2>
      <div className="dialog-body">{children}</div>
      <div className="dialog-actions">
        <button type="button" className="button button-quiet" onClick={onClose}>
          Keep it
        </button>
        <button type="button" className={`button ${tone === 'bad' ? 'button-danger' : 'button-primary'}`} disabled={pending} onClick={onConfirm}>
          {confirmLabel}
        </button>
      </div>
    </dialog>
  );
}
