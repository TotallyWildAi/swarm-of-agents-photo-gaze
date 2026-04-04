import React, { useState } from 'react';
import { Photo } from '../api';
import './PhotoMetadata.css';

interface PhotoMetadataProps {
  photo: Photo;
  isReference?: boolean;
}

/**
 * PhotoMetadata displays key photo information: filename, dimensions, file size,
 * quality score, and original/duplicate status. Expandable details available on demand.
 */
function PhotoMetadata({ photo, isReference = false }: PhotoMetadataProps) {
  const [expanded, setExpanded] = useState(false);

  const getQualityLabel = (score: number): string => {
    if (score >= 0.9) return 'Excellent';
    if (score >= 0.8) return 'Good';
    if (score >= 0.7) return 'Fair';
    return 'Poor';
  };

  const formatFileSize = (bytes?: number): string => {
    if (!bytes) return 'Unknown';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const statusLabel = photo.is_original ? 'Original' : photo.is_duplicate ? 'Duplicate' : 'Unknown';
  const statusClass = photo.is_original ? 'original' : photo.is_duplicate ? 'duplicate' : 'unknown';

  return (
    <div className={`photo-metadata ${isReference ? 'reference' : ''}`}>
      <div className="metadata-header">
        <div className="filename-section">
          <p className="filename">{photo.filename}</p>
          <span className={`status-badge ${statusClass}`}>{statusLabel}</span>
        </div>
        <button
          className="expand-button"
          onClick={() => setExpanded(!expanded)}
          aria-expanded={expanded}
        >
          {expanded ? '−' : '+'}
        </button>
      </div>

      <div className="metadata-summary">
        <div className="metadata-item">
          <span className="label">Quality:</span>
          <span className="value">{getQualityLabel(photo.quality_score)} ({(photo.quality_score * 100).toFixed(1)}%)</span>
        </div>
        {photo.dimensions && (
          <div className="metadata-item">
            <span className="label">Dimensions:</span>
            <span className="value">{photo.dimensions}</span>
          </div>
        )}
        {photo.file_size !== undefined && (
          <div className="metadata-item">
            <span className="label">Size:</span>
            <span className="value">{formatFileSize(photo.file_size)}</span>
          </div>
        )}
      </div>

      {expanded && (
        <div className="metadata-details">
          <div className="detail-item">
            <span className="label">Photo ID:</span>
            <span className="value">{photo.photo_id}</span>
          </div>
          <div className="detail-item">
            <span className="label">Path:</span>
            <span className="value path">{photo.path}</span>
          </div>
          {photo.similarity_score !== undefined && (
            <div className="detail-item">
              <span className="label">Similarity Score:</span>
              <span className="value">{(photo.similarity_score * 100).toFixed(1)}%</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default PhotoMetadata;
