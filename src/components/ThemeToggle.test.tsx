import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { ThemeProvider } from '../context/ThemeContext';
import { ThemeToggle } from './ThemeToggle';

describe('ThemeToggle', () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute('data-theme');
  });

  test('renders toggle button', () => {
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>
    );
    const button = screen.getByRole('button');
    expect(button).toBeInTheDocument();
  });

  test('displays sun emoji in dark mode', async () => {
    localStorage.setItem('theme', 'dark');
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>
    );

    await waitFor(() => {
      expect(screen.getByRole('button')).toHaveTextContent('☀️');
    });
  });

  test('displays moon emoji in light mode', async () => {
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>
    );

    await waitFor(() => {
      expect(screen.getByRole('button')).toHaveTextContent('🌙');
    });
  });

  test('toggles theme on button click', async () => {
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>
    );
    const button = screen.getByRole('button');

    await waitFor(() => {
      expect(button).toHaveTextContent('🌙');
    });

    fireEvent.click(button);

    await waitFor(() => {
      expect(button).toHaveTextContent('☀️');
    });
  });

  test('has correct aria-label', async () => {
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>
    );
    const button = screen.getByRole('button');

    await waitFor(() => {
      expect(button).toHaveAttribute('aria-label', 'Switch to dark mode');
    });
  });
});
