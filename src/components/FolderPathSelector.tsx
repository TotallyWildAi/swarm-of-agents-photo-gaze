import React, { useState } from 'react';
import { validateFolderPath, FolderValidationResponse } from '../api';
import './FolderPathSelector.css';

interface FolderPathSelectorProps {
  onFoldersSelected: (folders: string[]) => void;
  selectedFolders: string[];
}

/**
 * Component for selecting and validating local folder paths.
 * Displays validation errors and shows selected paths for user confirmation.
 */
function FolderPathSelector({ onFoldersSelected, selectedFolders }: FolderPathSelectorProps) {
  const [folderInput, setFolderInput] = useState('');
  const [validationError, setValidationError] = useState<string | null>(null);
  const [validationSuccess, setValidationSuccess] = useState<FolderValidationResponse | null>(null);
  const [isValidating, setIsValidating] = useState(false);

  const handleValidateFolder = async () => {
    if (!folderInput.trim()) {
      setValidationError('Please enter a folder path');
      return;
    }

    setIsValidating(true);
    setValidationError(null);
    setValidationSuccess(null);

    try {
      const result = await validateFolderPath(folderInput.trim());
      if (result.valid) {
        setValidationSuccess(result);
        setFolderInput('');
      } else {
        setValidationError(result.error || 'Folder validation failed');
      }
    } catch (err) {
      setValidationError(err instanceof Error ? err.message : 'Failed to validate folder');
    } finally {
      setIsValidating(false);
    }
  };

  const handleAddFolder = () => {
    if (validationSuccess && !selectedFolders.includes(validationSuccess.path)) {
      const updatedFolders = [...selectedFolders, validationSuccess.path];
      onFoldersSelected(updatedFolders);
      setValidationSuccess(null);
    }
  };

  const handleRemoveFolder = (path: string) => {
    const updatedFolders = selectedFolders.filter(f => f !== path);
    onFoldersSelected(updatedFolders);
  };

  const handleKeyPress = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      handleValidateFolder();
    }
  };

  return (
    <div className="folder-path-selector">
      <h2>Folder Selection</h2>
      <div className="folder-input-group">
        <label htmlFor="folder-input">Folder Path: </label>
        <input
          id="folder-input"
          type="text"
          value={folderInput}
          onChange={(e) => setFolderInput(e.target.value)}
          onKeyPress={handleKeyPress}
          placeholder="Enter folder path (e.g., /home/user/photos)"
          disabled={isValidating}
        />
        <button
          onClick={handleValidateFolder}
          disabled={isValidating || !folderInput.trim()}
          className="validate-btn"
        >
          {isValidating ? 'Validating...' : 'Validate'}
        </button>
      </div>

      {validationError && (
        <div className="validation-error">
          <span className="error-icon">✕</span>
          <p>{validationError}</p>
        </div>
      )}

      {validationSuccess && (
        <div className="validation-success">
          <span className="success-icon">✓</span>
          <div className="success-content">
            <p><strong>Path:</strong> {validationSuccess.path}</p>
            {validationSuccess.photo_count !== undefined && (
              <p><strong>Photos found:</strong> {validationSuccess.photo_count}</p>
            )}
          </div>
          <button onClick={handleAddFolder} className="add-btn">
            Add Folder
          </button>
        </div>
      )}

      {selectedFolders.length > 0 && (
        <div className="selected-folders">
          <h3>Selected Folders for Processing</h3>
          <ul>
            {selectedFolders.map((folder) => (
              <li key={folder}>
                <span className="folder-path">{folder}</span>
                <button
                  onClick={() => handleRemoveFolder(folder)}
                  className="remove-btn"
                  aria-label={`Remove ${folder}`}
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default FolderPathSelector;
