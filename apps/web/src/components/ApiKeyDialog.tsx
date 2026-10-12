import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { readApiKey, storeApiKey } from '@/lib/storage';

export function ApiKeyDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  const client = useQueryClient();
  const [value, setValue] = useState('');
  const [remember, setRemember] = useState(false);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  const save = (event: FormEvent) => {
    event.preventDefault();
    storeApiKey(value.trim() || null, remember);
    setValue('');
    void client.invalidateQueries();
    onClose();
  };

  const clear = () => {
    storeApiKey(null);
    void client.invalidateQueries();
    onClose();
  };

  return (
    <dialog ref={ref} className="dialog" onClose={onClose} aria-labelledby="api-key-title">
      <form onSubmit={save}>
        <h2 id="api-key-title">API key</h2>
        <div className="dialog-body">
          <p>This AgentForge server requires an API key. It is sent as a bearer token and kept in this browser tab unless you choose to remember it.</p>
          <label className="field">
            <span>Key</span>
            <input type="password" autoComplete="off" spellCheck={false} value={value} onChange={event => setValue(event.target.value)} placeholder={readApiKey() ? 'A key is saved; enter a new one to replace it' : 'af_…'} />
          </label>
          <label className="check">
            <input type="checkbox" checked={remember} onChange={event => setRemember(event.target.checked)} />
            Remember on this device
          </label>
        </div>
        <div className="dialog-actions">
          {readApiKey() ? (
            <button type="button" className="button button-quiet" onClick={clear}>
              Forget saved key
            </button>
          ) : null}
          <button type="button" className="button button-quiet" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="button button-primary" disabled={!value.trim()}>
            Save key
          </button>
        </div>
      </form>
    </dialog>
  );
}
