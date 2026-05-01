import React, { useEffect, useState } from 'react';
import { listTrash, recoverFromTrash, TrashItem } from '../api';
import './TrashPage.css';

interface TrashPageProps {
  onClose: () => void;
}

function formatSize(bytes: number | null): string {
  if (bytes == null) return '—';
  if (bytes >= 1_000_000) return `${(bytes / 1_000_000).toFixed(2)} MB`;
  return `${(bytes / 1_000).toFixed(1)} KB`;
}

function formatTrashedAt(ts: string): string {
  // ts is YYYYMMDD_HHMMSS in UTC; render as a readable local-ish stamp
  if (!/^\d{8}_\d{6}$/.test(ts)) return ts;
  const y = ts.slice(0, 4), mo = ts.slice(4, 6), d = ts.slice(6, 8);
  const h = ts.slice(9, 11), mi = ts.slice(11, 13), s = ts.slice(13, 15);
  return `${y}-${mo}-${d} ${h}:${mi}:${s} UTC`;
}

const TrashPage: React.FC<TrashPageProps> = ({ onClose }) => {
  const [items, setItems] = useState<TrashItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [recovering, setRecovering] = useState(false);
  const [statusMessage, setStatusMessage] = useState<string | null>(null);

  const refresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listTrash();
      setItems(data.items);
      // Drop any selections that no longer exist in the new list.
      setSelected(prev => {
        const valid = new Set(data.items.map(i => i.trash_path));
        const next = new Set<string>();
        prev.forEach(p => { if (valid.has(p)) next.add(p); });
        return next;
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { refresh(); }, []);

  const toggleOne = (trashPath: string) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(trashPath)) next.delete(trashPath);
      else next.add(trashPath);
      return next;
    });
  };

  const toggleAll = () => {
    if (selected.size === items.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(items.map(i => i.trash_path)));
    }
  };

  const handleRecover = async () => {
    if (selected.size === 0) return;
    setRecovering(true);
    setStatusMessage(null);
    try {
      const result = await recoverFromTrash(Array.from(selected));
      const errCount = result.errors?.length || 0;
      let msg = `Recovered ${result.recovered} photo${result.recovered === 1 ? '' : 's'}`;
      if (errCount > 0) {
        msg += ` · ${errCount} failed (`;
        msg += result.errors!.slice(0, 3).map(e => e.error).join('; ');
        if (errCount > 3) msg += `; …`;
        msg += ')';
      }
      setStatusMessage(msg);
      await refresh();
    } catch (e) {
      setStatusMessage(`Recovery failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setRecovering(false);
    }
  };

  const allSelected = items.length > 0 && selected.size === items.length;

  return (
    <div className="trash-page">
      <header className="trash-page__header">
        <button className="trash-page__back" onClick={onClose} aria-label="Back">←</button>
        <h2>Trash ({items.length})</h2>
        <div className="trash-page__actions">
          <button onClick={refresh} disabled={loading}>Refresh</button>
          <button
            className="trash-page__recover"
            onClick={handleRecover}
            disabled={selected.size === 0 || recovering}
          >
            {recovering ? 'Recovering…' : `Recover ${selected.size} selected`}
          </button>
        </div>
      </header>

      {statusMessage && (
        <div className="trash-page__status" role="status">{statusMessage}</div>
      )}

      {error && <div className="trash-page__error">{error}</div>}

      {loading ? (
        <p>Loading trash…</p>
      ) : items.length === 0 ? (
        <p className="trash-page__empty">Trash is empty.</p>
      ) : (
        <table className="trash-page__table">
          <thead>
            <tr>
              <th>
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={toggleAll}
                  aria-label="Select all"
                />
              </th>
              <th>Filename</th>
              <th>Original location</th>
              <th>Trashed at</th>
              <th>Size</th>
            </tr>
          </thead>
          <tbody>
            {items.map(item => (
              <tr key={item.trash_path}
                  className={selected.has(item.trash_path) ? 'is-selected' : ''}>
                <td>
                  <input
                    type="checkbox"
                    checked={selected.has(item.trash_path)}
                    onChange={() => toggleOne(item.trash_path)}
                    aria-label={`Select ${item.filename}`}
                  />
                </td>
                <td>{item.filename}</td>
                <td className="trash-page__path" title={item.original_path || ''}>
                  {item.original_path || <em>unknown</em>}
                </td>
                <td>{formatTrashedAt(item.trashed_at)}</td>
                <td>{formatSize(item.file_size)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
};

export default TrashPage;
