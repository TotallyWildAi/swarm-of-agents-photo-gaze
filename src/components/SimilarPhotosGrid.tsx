import React, { useEffect, useState } from 'react';
import { fetchSimilarPhotos } from '../api';
import './SimilarPhotosGrid.css';

interface Photo {
  photo_id: number;
  filename: string;
  path: string;
  quality_score?: number;
  similarity_score?: number;
}

interface SimilarPhotosGroup {
  group_id: string;
  reference_photo: Photo;
  similar_photos: Photo[];
}

interface SimilarPhotosGridProps {
  jobId: string;
}

const SimilarPhotosGrid: React.FC<SimilarPhotosGridProps> = ({ jobId }) => {
  const [groups, setGroups] = useState<SimilarPhotosGroup[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!jobId) {
      setGroups([]);
      setError(null);
      return;
    }

    const loadPhotos = async () => {
      setLoading(true);
      setError(null);
      try {
        const data = await fetchSimilarPhotos(jobId);
        setGroups(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error');
        setGroups([]);
      } finally {
        setLoading(false);
      }
    };

    loadPhotos();
  }, [jobId]);

  const getQualityLabel = (score: number): string => {
    if (score >= 0.85) return 'Excellent';
    if (score >= 0.7) return 'Good';
    if (score >= 0.5) return 'Fair';
    return 'Poor';
  };

  const getQualityClass = (score: number): string => {
    if (score >= 0.85) return 'quality-excellent';
    if (score >= 0.7) return 'quality-good';
    if (score >= 0.5) return 'quality-fair';
    return 'quality-poor';
  };

  if (!jobId) {
    return (
      <div className="similar-photos-container">
        <p>No job selected. Process a job to view similar photos.</p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="similar-photos-container">
        <p>Loading similar photos...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="similar-photos-container">
        <p className="error">Error: {error}</p>
      </div>
    );
  }

  if (groups.length === 0) {
    return (
      <div className="similar-photos-container">
        <p>No similar photos found.</p>
      </div>
    );
  }

  return (
    <div className="similar-photos-container">
      <h2 className="grid-title">Similar Photos ({groups.length} groups)</h2>
      {groups.map((group) => (
        <div key={group.group_id} className="group-container">
          <div className="group-header">
            <span>Reference Photo</span>
            <span className="match-count">{group.similar_photos.length} matches</span>
          </div>
          <div className="photos-grid">
            <div className="photo-card reference">
              <img
                src={group.reference_photo.path}
                alt={group.reference_photo.filename}
                className="thumbnail loading"
                onLoad={(e) => e.currentTarget.classList.remove('loading')}
              />
              <div className="photo-info">
                <div className="photo-filename">{group.reference_photo.filename}</div>
                {group.reference_photo.quality_score !== undefined && (
                  <div className="photo-score">
                    Quality: <strong>{getQualityLabel(group.reference_photo.quality_score)} ({(group.reference_photo.quality_score * 100).toFixed(1)}%)</strong>
                  </div>
                )}
              </div>
            </div>
            {group.similar_photos.map((photo) => (
              <div key={photo.photo_id} className="photo-card">
                <img
                  src={photo.path}
                  alt={photo.filename}
                  className="thumbnail loading"
                  onLoad={(e) => e.currentTarget.classList.remove('loading')}
                />
                <div className="photo-info">
                  <div className="photo-filename">{photo.filename}</div>
                  {photo.similarity_score !== undefined && (
                    <div className="photo-score">
                      Similarity: <strong>{(photo.similarity_score * 100).toFixed(1)}%</strong>
                    </div>
                  )}
                  {photo.quality_score !== undefined && (
                    <div className="quality-badge">
                      Quality: {getQualityLabel(photo.quality_score)} ({(photo.quality_score * 100).toFixed(1)}%)
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
};

export default SimilarPhotosGrid;
