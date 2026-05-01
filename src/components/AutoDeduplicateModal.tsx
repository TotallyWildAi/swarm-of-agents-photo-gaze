import React, { useEffect, useState } from 'react';
import {
  AutoDedupeResponse,
  autoDeduplicate,
  browsePath,
  BrowseResult,
  FolderEntry,
  listFolders,
} from '../api';
import './AutoDeduplicateModal.css';

interface AutoDeduplicateModalProps {
  threshold: number;
  onClose: () => void;
  onCompleted: () => void;
}

type Step = 'pick' | 'preview' | 'executing' | 'done';

const AutoDeduplicateModal: React.FC<AutoDeduplicateModalProps> = ({
  threshold,
  onClose,
  onCompleted,
}) => {
  const [step, setStep] = useState<Step>('pick');
  const [folders, setFolders] = useState<FolderEntry[]>([]);
  const [selected, setSelected] = useState<string>('');
  const [browseData, setBrowseData] = useState<BrowseResult | null>(null);
  const [browseLoading, setBrowseLoading] = useState(false);
  const [browseOpen, setBrowseOpen] = useState(false);
  const [plan, setPlan] = useState<AutoDedupeResponse | null>(null);
  const [result, setResult] = useState<AutoDedupeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listFolders().then(setFolders).catch(() => {});
  }, []);

  const navigateTo = async (p: string) => {
    setBrowseLoading(true);
    try {
      setBrowseData(await browsePath(p));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBrowseLoading(false);
    }
  };

  const openBrowser = () => {
    setBrowseOpen(true);
    navigateTo('/Users');
  };

  const requestPreview = async (folder: string) => {
    setError(null);
    try {
      const p = await autoDeduplicate(folder, threshold, true);
      setPlan(p);
      setStep('preview');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const confirmExecute = async () => {
    if (!selected) return;
    setStep('executing');
    setError(null);
    try {
      const r = await autoDeduplicate(selected, threshold, false);
      setResult(r);
      setStep('done');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setStep('preview');
    }
  };

  return (
    <div className="auto-dedupe-overlay" role="dialog" aria-modal="true">
      <div className="auto-dedupe-modal">
        <header>
          <h3>
            Auto-deduplicate {threshold >= 1.0 ? 'pure' : `≥ ${threshold.toFixed(2)}`} duplicates
          </h3>
          <button className="auto-dedupe-close" onClick={onClose} aria-label="Close">×</button>
        </header>

        {error && <div className="auto-dedupe-error">{error}</div>}

        {step === 'pick' && (
          <>
            <p>Pick a folder to set as the <b>source of truth</b>. All photos
              inside it (and its subfolders) are kept. Pure duplicates of those
              photos found in any other location will be moved to the trash.</p>

            {folders.length > 0 && (
              <>
                <p className="auto-dedupe-section-label">
                  Registered folders — click one to select:
                </p>
                <ul className="auto-dedupe-folder-grid"
                    role="radiogroup"
                    aria-label="Source of truth folder">
                  {folders.map(f => {
                    const isSelected = selected === f.path;
                    const segments = f.path.split('/').filter(Boolean);
                    const tail = segments[segments.length - 1] || f.path;
                    const head = segments.slice(0, -1).join('/');
                    return (
                      <li key={f.id}>
                        <label className={[
                          'auto-dedupe-folder-card',
                          isSelected ? 'is-selected' : '',
                          !f.is_accessible ? 'is-disabled' : '',
                        ].filter(Boolean).join(' ')}
                              title={f.path}>
                          <input
                            type="radio"
                            name="keep-folder"
                            value={f.path}
                            checked={isSelected}
                            onChange={e => setSelected(e.target.value)}
                            disabled={!f.is_accessible}
                            className="auto-dedupe-folder-radio"
                          />
                          <span className="auto-dedupe-folder-card-tick" aria-hidden="true">
                            {isSelected ? '✓' : ''}
                          </span>
                          <span className="auto-dedupe-folder-card-name">{tail}</span>
                          {head && (
                            <span className="auto-dedupe-folder-card-head">/{head}</span>
                          )}
                          {!f.is_accessible && (
                            <span className="auto-dedupe-folder-card-flag">
                              inaccessible
                            </span>
                          )}
                        </label>
                      </li>
                    );
                  })}
                </ul>
              </>
            )}

            <div className="auto-dedupe-row">
              <button onClick={openBrowser} disabled={browseOpen}>
                Browse for a subfolder or another path…
              </button>
              {selected && !folders.some(f => f.path === selected) && (
                <span className="auto-dedupe-custom-selected" title={selected}>
                  Selected: <code>{selected}</code>
                </span>
              )}
            </div>

            {browseOpen && (
              <div className="auto-dedupe-browser">
                <div className="auto-dedupe-browser-bar">
                  {browseData?.parent && (
                    <button onClick={() => navigateTo(browseData.parent!)}>↑ up</button>
                  )}
                  <code>{browseData?.path || '/'}</code>
                  <button onClick={() => {
                    if (browseData?.path) setSelected(browseData.path);
                    setBrowseOpen(false);
                  }}>Use this folder</button>
                </div>
                {browseLoading ? (
                  <p>Loading…</p>
                ) : (
                  <ul className="auto-dedupe-browser-dirs">
                    {(browseData?.dirs || []).map(d => (
                      <li key={d.name}>
                        <button onClick={() => navigateTo(`${browseData!.path.replace(/\/$/, '')}/${d.name}`)}>
                          📁 {d.name}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}

            <div className="auto-dedupe-actions">
              <button onClick={onClose}>Cancel</button>
              <button
                className="auto-dedupe-primary"
                disabled={!selected}
                onClick={() => requestPreview(selected)}
              >
                Preview
              </button>
            </div>
          </>
        )}

        {step === 'preview' && plan && (
          <>
            <p>
              Source of truth: <code>{plan.folder_path}</code>
            </p>
            <ul className="auto-dedupe-summary">
              <li><b>{plan.groups_processed}</b> duplicate groups will be deduplicated</li>
              <li><b>{plan.groups_skipped}</b> groups have no copy under the source-of-truth folder and will be left alone</li>
              <li><b>{plan.to_delete?.length || 0}</b> photos will be moved to trash and removed from the database + index</li>
              <li><b>{plan.kept.length}</b> photos will be kept</li>
            </ul>

            {(plan.to_delete?.length || 0) > 0 && plan.groups && (
              <details className="auto-dedupe-details">
                <summary>Show plan ({plan.groups.length} groups)</summary>
                <table>
                  <thead>
                    <tr><th>Keep</th><th>Delete</th></tr>
                  </thead>
                  <tbody>
                    {plan.groups.slice(0, 50).map(g => (
                      <tr key={g.kept_ids[0]}>
                        <td className="auto-dedupe-keep-cell">
                          <ul>
                            {g.kept_paths.map((p, i) =>
                              <li key={i}>{p || `#${g.kept_ids[i]}`}</li>
                            )}
                          </ul>
                        </td>
                        <td>
                          <ul>
                            {g.delete_paths.map((p, i) =>
                              <li key={i}>{p || `#${g.delete_ids[i]}`}</li>
                            )}
                          </ul>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {plan.groups.length > 50 && (
                  <p>… {plan.groups.length - 50} more groups not shown</p>
                )}
              </details>
            )}

            <div className="auto-dedupe-actions">
              <button onClick={() => setStep('pick')}>Back</button>
              <button
                className="auto-dedupe-primary auto-dedupe-danger"
                disabled={(plan.to_delete?.length || 0) === 0}
                onClick={confirmExecute}
              >
                Delete {plan.to_delete?.length || 0} duplicate{plan.to_delete?.length === 1 ? '' : 's'}
              </button>
            </div>
          </>
        )}

        {step === 'executing' && (
          <p>Deleting duplicates…</p>
        )}

        {step === 'done' && result && (
          <>
            <h4>Done</h4>
            <ul className="auto-dedupe-summary">
              <li><b>{result.deleted}</b> photos removed from database + Qdrant</li>
              <li><b>{result.moved_to_trash}</b> files moved to trash (recoverable)</li>
              <li><b>{result.kept.length}</b> kept</li>
              {(result.errors && result.errors.length > 0) && (
                <li className="auto-dedupe-error">
                  {result.errors.length} errors: {result.errors[0].error}
                </li>
              )}
            </ul>
            <div className="auto-dedupe-actions">
              <button className="auto-dedupe-primary" onClick={() => { onCompleted(); onClose(); }}>
                Close
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export default AutoDeduplicateModal;
