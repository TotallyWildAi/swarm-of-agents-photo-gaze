import React, { useState, useMemo, useEffect, useCallback } from 'react';
import { deduplicatePhotos } from '../api';
import './GroupDetailView.css';

interface Photo {
  photo_id: number;
  filename: string;
  path: string;
  quality_score?: number;
  similarity_score?: number;
  file_size?: number;
  file_path?: string;
  mime_type?: string;
  uploaded_at?: string;
  width?: number;
  height?: number;
  created_date?: string;
}

interface SimilarityGroup {
  group_id: string;
  reference_photo: Photo;
  similar_photos: Photo[];
  best_reasons?: string[];
}

interface GroupDetailViewProps {
  group: SimilarityGroup;
  onClose: () => void;
  onDeleted?: () => void;
}

const API_BASE = process.env.REACT_APP_API_URL || 'http://localhost:8000';

function formatBytes(bytes?: number): string {
  if (!bytes) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

const GroupDetailView: React.FC<GroupDetailViewProps> = ({ group, onClose, onDeleted }) => {
  const allPhotos = useMemo(() => {
    return [group.reference_photo, ...group.similar_photos];
  }, [group]);

  const bestPhotoId = useMemo(() => group.reference_photo.photo_id, [group]);

  // Auto-select all NON-best photos for deletion by default
  const [selectedPhotoIds, setSelectedPhotoIds] = useState<Set<number>>(() => {
    const ids = new Set<number>();
    for (const p of [group.reference_photo, ...group.similar_photos]) {
      if (p.photo_id !== group.reference_photo.photo_id) ids.add(p.photo_id);
    }
    return ids;
  });
  const [deduplicating, setDeduplicating] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [lightboxPhotoId, setLightboxPhotoId] = useState<number | null>(null);

  const [overrideBestId, setOverrideBestId] = useState<number | null>(null);

  const effectiveBestId = overrideBestId ?? bestPhotoId;

  const bestExplanation = overrideBestId
    ? ['Manually selected by you']
    : (group.best_reasons?.length ? group.best_reasons : ['First in similarity ranking']);

  const handlePhotoToggle = (photoId: number) => {
    const next = new Set(selectedPhotoIds);
    if (next.has(photoId)) next.delete(photoId);
    else next.add(photoId);
    setSelectedPhotoIds(next);
  };

  const handleDeduplicate = async () => {
    if (selectedPhotoIds.size === 0) {
      setMessage('Select at least one photo to delete.');
      return;
    }
    setDeduplicating(true);
    setMessage(null);
    try {
      const result = await deduplicatePhotos(Array.from(selectedPhotoIds));
      // Close modal and refresh the grid immediately
      if (onDeleted) onDeleted();
    } catch (error) {
      setMessage(`Error: ${error instanceof Error ? error.message : 'Failed to deduplicate'}`);
    } finally {
      setDeduplicating(false);
    }
  };

  const handleBackdropClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.target === e.currentTarget) onClose();
  };

  const currentLightboxPhoto = useMemo(
    () => allPhotos.find(p => p.photo_id === lightboxPhotoId) ?? null,
    [allPhotos, lightboxPhotoId]
  );

  const navigateLightbox = useCallback((dir: 1 | -1) => {
    if (lightboxPhotoId === null) return;
    const idx = allPhotos.findIndex(p => p.photo_id === lightboxPhotoId);
    if (idx < 0) return;
    const next = (idx + dir + allPhotos.length) % allPhotos.length;
    setLightboxPhotoId(allPhotos[next].photo_id);
  }, [lightboxPhotoId, allPhotos]);

  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if (e.key === 'Escape') {
      if (lightboxPhotoId !== null) setLightboxPhotoId(null);
      else onClose();
    } else if (lightboxPhotoId !== null && (e.key === 'ArrowRight' || e.key === 'ArrowDown')) {
      e.preventDefault();
      navigateLightbox(1);
    } else if (lightboxPhotoId !== null && (e.key === 'ArrowLeft' || e.key === 'ArrowUp')) {
      e.preventDefault();
      navigateLightbox(-1);
    }
  }, [lightboxPhotoId, onClose, navigateLightbox]);

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);

  return (
    <div className="group-detail-overlay" onClick={handleBackdropClick}>
      {lightboxPhotoId !== null && currentLightboxPhoto && (
        <div className="lightbox-overlay" onClick={() => setLightboxPhotoId(null)}>
          <img
            src={`${API_BASE}/photos/${lightboxPhotoId}/full`}
            alt="Full resolution"
            className="lightbox-image"
            onClick={(e) => e.stopPropagation()}
          />
          <button className="lightbox-close" onClick={() => setLightboxPhotoId(null)}>✕</button>
          <button className="lightbox-nav lightbox-prev" onClick={(e) => { e.stopPropagation(); navigateLightbox(-1); }}>‹</button>
          <button className="lightbox-nav lightbox-next" onClick={(e) => { e.stopPropagation(); navigateLightbox(1); }}>›</button>
          <div className="lightbox-info" onClick={(e) => e.stopPropagation()}>
            <strong>{currentLightboxPhoto.filename}</strong>
            <span>
              {currentLightboxPhoto.width && currentLightboxPhoto.height && `${currentLightboxPhoto.width}×${currentLightboxPhoto.height}`}
              {currentLightboxPhoto.file_size && ` · ${formatBytes(currentLightboxPhoto.file_size)}`}
              {currentLightboxPhoto.mime_type && ` · ${currentLightboxPhoto.mime_type}`}
            </span>
            {currentLightboxPhoto.created_date && (
              <span>Created: {new Date(currentLightboxPhoto.created_date).toLocaleString()}</span>
            )}
            <span style={{ opacity: 0.6 }}>
              {allPhotos.findIndex(p => p.photo_id === lightboxPhotoId) + 1} / {allPhotos.length} · ← → to navigate · Esc to close
            </span>
          </div>
        </div>
      )}
      <div className="group-detail-modal">
        <div className="detail-header">
          <h2>Duplicate Group &middot; {allPhotos.length} photos</h2>
          <button className="close-button" onClick={onClose} aria-label="Close">✕</button>
        </div>

        <div className="best-explanation">
          <strong>★ Best photo kept:</strong> {allPhotos.find(p => p.photo_id === effectiveBestId)?.filename ?? '?'}
          <ul>
            {bestExplanation.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </div>

        <div className="detail-content">
          <div className="photos-grid">
            {allPhotos.map((photo) => {
              const isBest = photo.photo_id === effectiveBestId;
              const isSelected = selectedPhotoIds.has(photo.photo_id);
              return (
                <div
                  key={photo.photo_id}
                  className={`photo-card ${isBest ? 'best-photo' : ''} ${isSelected ? 'selected' : ''}`}
                >
                  {isBest && <div className="best-indicator">★ Best</div>}
                  <img
                    src={photo.path}
                    alt={photo.filename}
                    className="detail-image"
                    onClick={() => setLightboxPhotoId(photo.photo_id)}
                    title="Click for full resolution"
                    style={{ cursor: 'zoom-in' }}
                  />
                  <div className="photo-metadata">
                    <p className="filename" title={photo.filename}><strong>{photo.filename}</strong></p>
                    <table className="meta-table">
                      <tbody>
                        {photo.similarity_score != null && (
                          <tr><td>Similarity</td><td>{(photo.similarity_score * 100).toFixed(1)}%</td></tr>
                        )}
                        {photo.width && photo.height && (
                          <tr><td>Resolution</td><td>{photo.width} x {photo.height}</td></tr>
                        )}
                        <tr><td>File size</td><td>{formatBytes(photo.file_size)}</td></tr>
                        {photo.mime_type && <tr><td>Type</td><td>{photo.mime_type}</td></tr>}
                        {photo.created_date && (
                          <tr><td>Created</td><td>{new Date(photo.created_date).toLocaleString()}</td></tr>
                        )}
                        {photo.file_path && (
                          <tr><td>Path</td><td className="path-cell" title={photo.file_path}>{photo.file_path.split('/').pop()}</td></tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                  <div className="card-actions">
                    {isBest && !isSelected ? (
                      <div className="fate-badge fate-keep">★ KEEPING — Best photo</div>
                    ) : isSelected ? (
                      <div className="fate-badge fate-delete" onClick={() => handlePhotoToggle(photo.photo_id)}>
                        🗑 DELETING — <span className="fate-toggle-hint">click to keep</span>
                      </div>
                    ) : (
                      <div className="fate-badge fate-keep-manual" onClick={() => handlePhotoToggle(photo.photo_id)}>
                        ✓ KEEPING — <span className="fate-toggle-hint">click to delete</span>
                      </div>
                    )}
                    {!isBest && (
                      <button
                        className="mark-best-btn"
                        onClick={() => {
                          setOverrideBestId(photo.photo_id);
                          const next = new Set(allPhotos.map(p => p.photo_id));
                          next.delete(photo.photo_id);
                          setSelectedPhotoIds(next);
                        }}
                        title="Override automatic selection and keep this photo instead"
                      >
                        Mark as Best
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div className="detail-footer">
          {message && (
            <p className={`message ${message.includes('Error') ? 'error' : 'success'}`}>
              {message}
            </p>
          )}
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            <button
              className="deduplicate-button"
              onClick={handleDeduplicate}
              disabled={selectedPhotoIds.size === 0 || deduplicating}
            >
              {deduplicating ? 'Deleting...' : `Delete ${selectedPhotoIds.size} photo(s)`}
            </button>
            <button
              className="select-all-btn"
              onClick={() => {
                const allIds = new Set(allPhotos.map(p => p.photo_id));
                setSelectedPhotoIds(allIds);
              }}
              title="Select every photo in this group for deletion, including the best"
            >
              Select all (including best)
            </button>
            <button
              className="select-all-btn"
              onClick={() => {
                setSelectedPhotoIds(new Set());
              }}
            >
              Deselect all
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default GroupDetailView;
