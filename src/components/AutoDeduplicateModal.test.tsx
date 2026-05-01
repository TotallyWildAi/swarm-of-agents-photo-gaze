import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import AutoDeduplicateModal from './AutoDeduplicateModal';
import * as api from '../api';

jest.mock('../api');

const mockListFolders = api.listFolders as jest.MockedFunction<typeof api.listFolders>;
const mockAuto = api.autoDeduplicate as jest.MockedFunction<typeof api.autoDeduplicate>;
const mockBrowse = api.browsePath as jest.MockedFunction<typeof api.browsePath>;

describe('AutoDeduplicateModal', () => {
  beforeEach(() => {
    mockListFolders.mockReset();
    mockAuto.mockReset();
    mockBrowse.mockReset();
    mockListFolders.mockResolvedValue([
      { id: 1, path: '/photos/keep', is_accessible: true, supported_formats_found: ['.jpg'] },
      { id: 2, path: '/photos/other', is_accessible: true, supported_formats_found: ['.jpg'] },
    ]);
  });

  it('lists registered folders and disables Preview until one is selected', async () => {
    render(<AutoDeduplicateModal threshold={1.0} onClose={() => {}} onCompleted={() => {}} />);
    await screen.findByText('/photos/keep');
    expect(screen.getByRole('button', { name: 'Preview' })).toBeDisabled();
    await userEvent.click(screen.getByDisplayValue('/photos/keep'));
    expect(screen.getByRole('button', { name: 'Preview' })).toBeEnabled();
  });

  it('requests dry-run preview, shows summary, then executes on confirm', async () => {
    mockAuto
      .mockResolvedValueOnce({
        dry_run: true, threshold: 1.0, folder_path: '/photos/keep',
        groups_processed: 2, groups_skipped: 1, kept: [10, 11],
        to_delete: [20, 21, 22], groups: [
          { keeper_id: 10, keeper_path: '/photos/keep/a.jpg', delete_ids: [20], delete_paths: ['/photos/other/a.jpg'] },
          { keeper_id: 11, keeper_path: '/photos/keep/b.jpg', delete_ids: [21, 22],
            delete_paths: ['/photos/other/b.jpg', '/photos/keep/b_copy.jpg'] },
        ],
      })
      .mockResolvedValueOnce({
        dry_run: false, threshold: 1.0, folder_path: '/photos/keep',
        groups_processed: 2, groups_skipped: 1, kept: [10, 11],
        deleted: 3, moved_to_trash: 3, errors: null,
      });

    const onCompleted = jest.fn();
    render(<AutoDeduplicateModal threshold={1.0} onClose={() => {}} onCompleted={onCompleted} />);
    await userEvent.click(await screen.findByDisplayValue('/photos/keep'));
    await userEvent.click(screen.getByRole('button', { name: 'Preview' }));

    // Preview step shows the planned counts
    await screen.findByText(/2/, { selector: 'b' });
    expect(mockAuto).toHaveBeenLastCalledWith('/photos/keep', 1.0, true);
    expect(screen.getByRole('button', { name: /Delete 3 duplicates/ })).toBeEnabled();

    // Confirm execute
    await userEvent.click(screen.getByRole('button', { name: /Delete 3 duplicates/ }));
    await waitFor(() =>
      expect(mockAuto).toHaveBeenLastCalledWith('/photos/keep', 1.0, false)
    );
    await screen.findByText(/3/, { selector: 'b' });
    expect(screen.getByText(/photos removed from database/)).toBeInTheDocument();
  });

  it('disables Delete button when plan has nothing to delete', async () => {
    mockAuto.mockResolvedValueOnce({
      dry_run: true, threshold: 1.0, folder_path: '/photos/keep',
      groups_processed: 0, groups_skipped: 5, kept: [], to_delete: [],
      groups: [],
    });
    render(<AutoDeduplicateModal threshold={1.0} onClose={() => {}} onCompleted={() => {}} />);
    await userEvent.click(await screen.findByDisplayValue('/photos/keep'));
    await userEvent.click(screen.getByRole('button', { name: 'Preview' }));
    const btn = await screen.findByRole('button', { name: /Delete 0 duplicates/ });
    expect(btn).toBeDisabled();
  });

  it('renders the threshold in the header', async () => {
    render(<AutoDeduplicateModal threshold={1.0} onClose={() => {}} onCompleted={() => {}} />);
    expect(screen.getByText(/pure duplicates/)).toBeInTheDocument();

    render(<AutoDeduplicateModal threshold={0.95} onClose={() => {}} onCompleted={() => {}} />);
    // For sub-1.0 thresholds the header reads "≥ 0.95 duplicates"
    expect(screen.getByText(/≥ 0\.95 duplicates/)).toBeInTheDocument();
  });

  it('shows error on backend failure', async () => {
    mockAuto.mockRejectedValueOnce(new Error('boom'));
    render(<AutoDeduplicateModal threshold={1.0} onClose={() => {}} onCompleted={() => {}} />);
    await userEvent.click(await screen.findByDisplayValue('/photos/keep'));
    await userEvent.click(screen.getByRole('button', { name: 'Preview' }));
    expect(await screen.findByText('boom')).toBeInTheDocument();
  });
});
