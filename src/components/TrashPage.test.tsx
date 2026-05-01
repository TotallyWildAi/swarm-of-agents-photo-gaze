import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import TrashPage from './TrashPage';
import * as api from '../api';

jest.mock('../api');

const mockListTrash = api.listTrash as jest.MockedFunction<typeof api.listTrash>;
const mockRecover = api.recoverFromTrash as jest.MockedFunction<typeof api.recoverFromTrash>;

describe('TrashPage', () => {
  beforeEach(() => {
    mockListTrash.mockReset();
    mockRecover.mockReset();
  });

  it('renders empty state when trash is empty', async () => {
    mockListTrash.mockResolvedValue({ items: [], trash_dir: '/trash' });
    render(<TrashPage onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText(/Trash is empty/)).toBeInTheDocument());
  });

  it('renders each trash item as a card with a thumbnail and details', async () => {
    mockListTrash.mockResolvedValue({
      items: [
        {
          trash_path: '/trash/20260101_100000_1_a.jpg',
          original_path: '/photos/a.jpg',
          filename: 'a.jpg',
          trashed_at: '20260101_100000',
          file_size: 1500,
        },
        {
          trash_path: '/trash/20260101_100000_2_b.jpg',
          original_path: '/photos/b.jpg',
          filename: 'b.jpg',
          trashed_at: '20260101_100000',
          file_size: 2_500_000,
        },
      ],
      trash_dir: '/trash',
    });
    render(<TrashPage onClose={() => {}} />);
    // Filenames + sizes still rendered (under the thumbnail now).
    expect(await screen.findByText('a.jpg')).toBeInTheDocument();
    expect(screen.getByText('b.jpg')).toBeInTheDocument();
    expect(screen.getByText(/2\.50 MB/)).toBeInTheDocument();
    expect(screen.getByText(/1\.5 KB/)).toBeInTheDocument();
    // Original-path detail rendered under each card.
    expect(screen.getByText('/photos/a.jpg')).toBeInTheDocument();
    expect(screen.getByText('/photos/b.jpg')).toBeInTheDocument();
  });

  it('renders an <img> thumbnail per item pointing at /trash/thumbnail', async () => {
    mockListTrash.mockResolvedValue({
      items: [
        {
          trash_path: '/trash/20260101_100000_1_a.jpg',
          original_path: '/photos/a.jpg',
          filename: 'a.jpg',
          trashed_at: '20260101_100000',
          file_size: 1500,
        },
      ],
      trash_dir: '/trash',
    });
    render(<TrashPage onClose={() => {}} />);
    const img = (await screen.findByAltText('a.jpg')) as HTMLImageElement;
    expect(img.tagName).toBe('IMG');
    // src must reach /trash/thumbnail with the trash_path URL-encoded as a
    // query parameter — the backend uses `path=` and rejects anything not
    // resolving inside TRASH_DIR.
    expect(img.src).toContain('/trash/thumbnail?path=');
    expect(img.src).toContain(
      encodeURIComponent('/trash/20260101_100000_1_a.jpg'),
    );
  });

  it('recovers selected items and refreshes the list', async () => {
    mockListTrash
      .mockResolvedValueOnce({
        items: [
          {
            trash_path: '/trash/20260101_100000_1_a.jpg',
            original_path: '/photos/a.jpg',
            filename: 'a.jpg',
            trashed_at: '20260101_100000',
            file_size: 1500,
          },
        ],
        trash_dir: '/trash',
      })
      .mockResolvedValueOnce({ items: [], trash_dir: '/trash' });
    mockRecover.mockResolvedValue({
      recovered: 1,
      items: [{ trash_path: '/trash/20260101_100000_1_a.jpg', restored_to: '/photos/a.jpg' }],
      errors: null,
    });

    render(<TrashPage onClose={() => {}} />);
    const checkbox = await screen.findByLabelText('Select a.jpg');
    await userEvent.click(checkbox);

    const recoverBtn = screen.getByRole('button', { name: /Recover 1 selected/ });
    await userEvent.click(recoverBtn);

    await waitFor(() => {
      expect(mockRecover).toHaveBeenCalledWith(['/trash/20260101_100000_1_a.jpg']);
      expect(screen.getByText(/Recovered 1 photo/)).toBeInTheDocument();
    });
    // After successful recover the list refreshes and shows empty state
    await waitFor(() => expect(screen.getByText(/Trash is empty/)).toBeInTheDocument());
  });

  it('disables Recover button when nothing is selected', async () => {
    mockListTrash.mockResolvedValue({
      items: [
        {
          trash_path: '/trash/x.jpg',
          original_path: '/photos/x.jpg',
          filename: 'x.jpg',
          trashed_at: '20260101_100000',
          file_size: 100,
        },
      ],
      trash_dir: '/trash',
    });
    render(<TrashPage onClose={() => {}} />);
    const recoverBtn = await screen.findByRole('button', { name: /Recover 0 selected/ });
    expect(recoverBtn).toBeDisabled();
  });

  it('toggles select-all', async () => {
    mockListTrash.mockResolvedValue({
      items: [
        { trash_path: '/t/a', original_path: '/o/a', filename: 'a.jpg', trashed_at: '20260101_100000', file_size: 1 },
        { trash_path: '/t/b', original_path: '/o/b', filename: 'b.jpg', trashed_at: '20260101_100000', file_size: 1 },
      ],
      trash_dir: '/trash',
    });
    render(<TrashPage onClose={() => {}} />);
    const selectAll = await screen.findByLabelText('Select all');
    await userEvent.click(selectAll);
    expect(screen.getByRole('button', { name: /Recover 2 selected/ })).toBeEnabled();
    await userEvent.click(selectAll);
    expect(screen.getByRole('button', { name: /Recover 0 selected/ })).toBeDisabled();
  });

  it('shows partial-failure status from recover response', async () => {
    mockListTrash.mockResolvedValue({
      items: [
        { trash_path: '/t/a', original_path: '/o/a', filename: 'a.jpg', trashed_at: '20260101_100000', file_size: 1 },
        { trash_path: '/t/b', original_path: '/o/b', filename: 'b.jpg', trashed_at: '20260101_100000', file_size: 1 },
      ],
      trash_dir: '/trash',
    });
    mockRecover.mockResolvedValue({
      recovered: 1,
      items: [{ trash_path: '/t/a', restored_to: '/o/a' }],
      errors: [{ trash_path: '/t/b', error: 'a file already exists at /o/b' }],
    });

    render(<TrashPage onClose={() => {}} />);
    await userEvent.click(await screen.findByLabelText('Select all'));
    await userEvent.click(screen.getByRole('button', { name: /Recover 2 selected/ }));
    await waitFor(() =>
      expect(screen.getByText(/Recovered 1 photo · 1 failed/)).toBeInTheDocument()
    );
  });
});
