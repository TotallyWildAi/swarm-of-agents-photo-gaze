import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import App from './App';
import * as api from './api';

// Mock the api module
jest.mock('./api');

describe('App Component', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('renders app header', () => {
    (api.fetchHealth as jest.Mock).mockResolvedValue({ status: 'healthy' });
    render(<App />);
    const header = screen.getByText('Full-Stack Application');
    expect(header).toBeInTheDocument();
  });

  test('displays loading state initially', () => {
    (api.fetchHealth as jest.Mock).mockImplementation(
      () => new Promise(() => {}) // Never resolves
    );
    render(<App />);
    expect(screen.getByText('Loading...')).toBeInTheDocument();
  });

  test('displays health status when API call succeeds', async () => {
    (api.fetchHealth as jest.Mock).mockResolvedValue({ status: 'healthy' });
    render(<App />);
    await waitFor(() => {
      expect(screen.getByText(/Backend Status:/)).toBeInTheDocument();
      expect(screen.getByText('healthy')).toBeInTheDocument();
    });
  });

  test('displays error message when API call fails', async () => {
    const errorMessage = 'Network error';
    (api.fetchHealth as jest.Mock).mockRejectedValue(new Error(errorMessage));
    render(<App />);
    await waitFor(() => {
      expect(screen.getByText(new RegExp(errorMessage))).toBeInTheDocument();
    });
  });
});
