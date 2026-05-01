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
            <p>Select the folder you want to <b>keep</b> duplicates in. Pure
              duplicates of these photos in any other folder will be deleted.
              Extra copies inside the keep folder will also be reduced to one.</p>

            {folders.length > 0 && (
              <>
                <p className="auto-dedupe-section-label">Registered folders:</p>
                <ul className="auto-dedupe-folder-list">
                  {folders.map(f => (
                    <li key={f.id}>
                      <label>
                        <input
                          type="radio"
                          name="keep-folder"
                          value={f.path}
                          checked={selected === f.path}
                          onChange={e => setSelected(e.target.value)}
                          disabled={!f.is_accessible}
                        />
                        <span className="auto-dedupe-folder-path">{f.path}</span>
                        {!f.is_accessible && <em> (inaccessible)</em>}
                      </label>
                    </li>
                  ))}
                </ul>
              </>
            )}

            <div className="auto-dedupe-row">
              <button onClick={openBrowser} disabled={browseOpen}>
                Browse for another folder…
              </button>
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
              Keep folder: <code>{plan.folder_path}</code>
            </p>
            <ul className="auto-dedupe-summary">
              <li><b>{plan.groups_processed}</b> duplicate groups will be deduplicated</li>
              <li><b>{plan.groups_skipped}</b> groups have no copy in the keep folder and will be left alone</li>
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
                      <tr key={g.keeper_id}>
                        <td className="auto-dedupe-keep-cell">{g.keeper_path || `#${g.keeper_id}`}</td>
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
