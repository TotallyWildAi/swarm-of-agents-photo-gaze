import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import FolderPathSelector from './FolderPathSelector';
import * as api from '../api';

jest.mock('../api');

describe('FolderPathSelector Component', () => {
  const mockOnFoldersSelected = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('renders folder path selector with input field', () => {
    render(<FolderPathSelector onFoldersSelected={mockOnFoldersSelected} selectedFolders={[]} />);
    expect(screen.getByText('Folder Selection')).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/Enter folder path/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Validate/i })).toBeInTheDocument();
  });

  test('displays validation error when folder path is empty', async () => {
    render(<FolderPathSelector onFoldersSelected={mockOnFoldersSelected} selectedFolders={[]} />);
    const validateBtn = screen.getByRole('button', { name: /Validate/i });
    fireEvent.click(validateBtn);
    await waitFor(() => {
      expect(screen.getByText('Please enter a folder path')).toBeInTheDocument();
    });
  });

  test('displays validation error from API', async () => {
    (api.validateFolderPath as jest.Mock).mockRejectedValue(
      new Error('Folder not found')
    );
    render(<FolderPathSelector onFoldersSelected={mockOnFoldersSelected} selectedFolders={[]} />);
    const input = screen.getByPlaceholderText(/Enter folder path/);
    const validateBtn = screen.getByRole('button', { name: /Validate/i });
    
    await userEvent.type(input, '/invalid/path');
    fireEvent.click(validateBtn);
    
    await waitFor(() => {
      expect(screen.getByText('Folder not found')).toBeInTheDocument();
    });
  });

  test('displays validation success with photo count', async () => {
    (api.validateFolderPath as jest.Mock).mockResolvedValue({
      valid: true,
      path: '/home/user/photos',
      photo_count: 42,
    });
    render(<FolderPathSelector onFoldersSelected={mockOnFoldersSelected} selectedFolders={[]} />);
    const input = screen.getByPlaceholderText(/Enter folder path/);
    const validateBtn = screen.getByRole('button', { name: /Validate/i });
    
    await userEvent.type(input, '/home/user/photos');
    fireEvent.click(validateBtn);
    
    await waitFor(() => {
      expect(screen.getByText('/home/user/photos')).toBeInTheDocument();
      expect(screen.getByText('Photos found: 42')).toBeInTheDocument();
    });
  });

  test('adds folder to selected folders when Add Folder button clicked', async () => {
    (api.validateFolderPath as jest.Mock).mockResolvedValue({
      valid: true,
      path: '/home/user/photos',
      photo_count: 10,
    });
    render(<FolderPathSelector onFoldersSelected={mockOnFoldersSelected} selectedFolders={[]} />);
    const input = screen.getByPlaceholderText(/Enter folder path/);
    const validateBtn = screen.getByRole('button', { name: /Validate/i });
    
    await userEvent.type(input, '/home/user/photos');
    fireEvent.click(validateBtn);
    
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Add Folder/i })).toBeInTheDocument();
    });
    
    const addBtn = screen.getByRole('button', { name: /Add Folder/i });
    fireEvent.click(addBtn);
    
    expect(mockOnFoldersSelected).toHaveBeenCalledWith(['/home/user/photos']);
  });

  test('displays selected folders with remove buttons', () => {
    const selectedFolders = ['/home/user/photos', '/mnt/external/images'];
    render(
      <FolderPathSelector
        onFoldersSelected={mockOnFoldersSelected}
        selectedFolders={selectedFolders}
      />
    );
    
    expect(screen.getByText('Selected Folders for Processing')).toBeInTheDocument();
    expect(screen.getByText('/home/user/photos')).toBeInTheDocument();
    expect(screen.getByText('/mnt/external/images')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: /Remove/i })).toHaveLength(2);
  });

  test('removes folder when Remove button clicked', () => {
    const selectedFolders = ['/home/user/photos', '/mnt/external/images'];
    render(
      <FolderPathSelector
        onFoldersSelected={mockOnFoldersSelected}
        selectedFolders={selectedFolders}
      />
    );
    
    const removeButtons = screen.getAllByRole('button', { name: /Remove/i });
    fireEvent.click(removeButtons[0]);
    
    expect(mockOnFoldersSelected).toHaveBeenCalledWith(['/mnt/external/images']);
  });

  test('validates folder on Enter key press', async () => {
    (api.validateFolderPath as jest.Mock).mockResolvedValue({
      valid: true,
      path: '/home/user/photos',
      photo_count: 5,
    });
    render(<FolderPathSelector onFoldersSelected={mockOnFoldersSelected} selectedFolders={[]} />);
    const input = screen.getByPlaceholderText(/Enter folder path/) as HTMLInputElement;
    
    await userEvent.type(input, '/home/user/photos');
    fireEvent.keyPress(input, { key: 'Enter', code: 'Enter', charCode: 13 });
    
    await waitFor(() => {
      expect(api.validateFolderPath).toHaveBeenCalledWith('/home/user/photos');
    });
  });

  test('disables validate button when input is empty', () => {
    render(<FolderPathSelector onFoldersSelected={mockOnFoldersSelected} selectedFolders={[]} />);
    const validateBtn = screen.getByRole('button', { name: /Validate/i }) as HTMLButtonElement;
    expect(validateBtn.disabled).toBe(true);
  });

  test('enables validate button when input has text', async () => {
    render(<FolderPathSelector onFoldersSelected={mockOnFoldersSelected} selectedFolders={[]} />);
    const input = screen.getByPlaceholderText(/Enter folder path/);
    const validateBtn = screen.getByRole('button', { name: /Validate/i }) as HTMLButtonElement;
    
    expect(validateBtn.disabled).toBe(true);
    await userEvent.type(input, '/home/user/photos');
    expect(validateBtn.disabled).toBe(false);
  });

  test('clears input field after successful validation', async () => {
    (api.validateFolderPath as jest.Mock).mockResolvedValue({
      valid: true,
      path: '/home/user/photos',
      photo_count: 10,
    });
    render(<FolderPathSelector onFoldersSelected={mockOnFoldersSelected} selectedFolders={[]} />);
    const input = screen.getByPlaceholderText(/Enter folder path/) as HTMLInputElement;
    const validateBtn = screen.getByRole('button', { name: /Validate/i });
    
    await userEvent.type(input, '/home/user/photos');
    fireEvent.click(validateBtn);
    
    await waitFor(() => {
      expect(input.value).toBe('');
    });
  });

  test('prevents duplicate folder selection', async () => {
    (api.validateFolderPath as jest.Mock).mockResolvedValue({
      valid: true,
      path: '/home/user/photos',
      photo_count: 10,
    });
    const selectedFolders = ['/home/user/photos'];
    render(
      <FolderPathSelector
        onFoldersSelected={mockOnFoldersSelected}
        selectedFolders={selectedFolders}
      />
    );
    const input = screen.getByPlaceholderText(/Enter folder path/);
    const validateBtn = screen.getByRole('button', { name: /Validate/i });
    
    await userEvent.type(input, '/home/user/photos');
    fireEvent.click(validateBtn);
    
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /Add Folder/i })).toBeInTheDocument();
    });
    
    const addBtn = screen.getByRole('button', { name: /Add Folder/i });
    fireEvent.click(addBtn);
    
    // Should not add duplicate
    expect(mockOnFoldersSelected).not.toHaveBeenCalled();
  });
});
