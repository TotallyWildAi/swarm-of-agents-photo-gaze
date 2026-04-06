import React, { useState, useMemo } from 'react';
import { deduplicatePhotos } from '../api';
import './GroupDetailView.css';

interface Photo {
  photo_id: number;
  filename: string;
  path: string;
  quality_score?: number;
  similarity_score?: number;
}

interface SimilarityGroup {
  group_id: string;
  reference_photo: Photo;
  similar_photos: Photo[];
}

interface GroupDetailViewProps {
  group: SimilarityGroup;
  onClose: () => void;
  onDeleted?: () => void;
}

/**
 * Full-screen detail view for a similarity group.
 * Shows all images with metadata, best-photo indicator,
 * checkbox selection, and a deduplicate button.
 */
const API_BASE = process.env.REACT_APP_API_URL || 'http://localhost:8000';

const GroupDetailView: React.FC<GroupDetailViewProps> = ({ group, onClose, onDeleted }) => {
  const [selectedPhotoIds, setSelectedPhotoIds] = useState<Set<number>>(new Set());
  const [deduplicating, setDeduplicating] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [lightboxPhotoId, setLightboxPhotoId] = useState<number | null>(null);

  const allPhotos = useMemo(() => {
    return [group.reference_photo, ...group.similar_photos];
  }, [group]);

  // Best photo = reference (highest quality / first in the group)
  const bestPhotoId = useMemo(() => {
    return group.reference_photo.photo_id;
  }, [group]);

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
      setMessage(`Deleted ${result.deleted} photo(s) from database.`);
      setSelectedPhotoIds(new Set());
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

  return (
    <div className="group-detail-overlay" onClick={handleBackdropClick}>
      {lightboxPhotoId !== null && (
        <div
          className="lightbox-overlay"
          onClick={() => setLightboxPhotoId(null)}
        >
          <img
            src={`${API_BASE}/photos/${lightboxPhotoId}/full`}
            alt="Full resolution"
            className="lightbox-image"
            onClick={(e) => e.stopPropagation()}
          />
          <button className="lightbox-close" onClick={() => setLightboxPhotoId(null)}>✕</button>
        </div>
      )}
      <div className="group-detail-modal">
        <div className="detail-header">
          <h2>Group: {group.group_id}</h2>
          <button className="close-button" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>

        <div className="detail-content">
          <div className="photos-grid">
            {allPhotos.map((photo) => {
              const isBest = photo.photo_id === bestPhotoId;
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
                    <p className="filename"><strong>{photo.filename}</strong></p>
                    {photo.similarity_score != null && (
                      <p>Similarity: {(photo.similarity_score * 100).toFixed(1)}%</p>
                    )}
                  </div>
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => handlePhotoToggle(photo.photo_id)}
                      disabled={isBest}
                      title={isBest ? 'Cannot delete the best photo' : ''}
                    />
                    {isBest ? 'Best (keep)' : 'Mark for deletion'}
                  </label>
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
          <button
            className="deduplicate-button"
            onClick={handleDeduplicate}
            disabled={selectedPhotoIds.size === 0 || deduplicating}
          >
            {deduplicating ? 'Deleting...' : `Delete Selected (${selectedPhotoIds.size})`}
          </button>
        </div>
      </div>
    </div>
  );
};

export default GroupDetailView;
