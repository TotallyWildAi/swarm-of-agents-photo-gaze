import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { ThemeProvider, useTheme } from './ThemeContext';

// Test component that uses the theme hook
const TestComponent = () => {
  const { theme, toggleTheme } = useTheme();
  return (
    <div>
      <span data-testid="theme-display">{theme}</span>
      <button onClick={toggleTheme} data-testid="toggle-btn">
        Toggle
      </button>
    </div>
  );
};

describe('ThemeContext', () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute('data-theme');
  });

  test('provides theme context to children', () => {
    render(
      <ThemeProvider>
        <TestComponent />
      </ThemeProvider>
    );
    expect(screen.getByTestId('theme-display')).toBeInTheDocument();
  });

  test('toggleTheme switches between light and dark', async () => {
    render(
      <ThemeProvider>
        <TestComponent />
      </ThemeProvider>
    );
    const display = screen.getByTestId('theme-display');
    const button = screen.getByTestId('toggle-btn');

    await waitFor(() => {
      expect(display.textContent).toBe('light');
    });

    fireEvent.click(button);

    await waitFor(() => {
      expect(display.textContent).toBe('dark');
    });

    fireEvent.click(button);

    await waitFor(() => {
      expect(display.textContent).toBe('light');
    });
  });

  test('persists theme to localStorage', async () => {
    render(
      <ThemeProvider>
        <TestComponent />
      </ThemeProvider>
    );
    const button = screen.getByTestId('toggle-btn');

    fireEvent.click(button);

    await waitFor(() => {
      expect(localStorage.getItem('theme')).toBe('dark');
    });
  });

  test('loads theme from localStorage on mount', async () => {
    localStorage.setItem('theme', 'dark');

    render(
      <ThemeProvider>
        <TestComponent />
      </ThemeProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('theme-display').textContent).toBe('dark');
    });
  });

  test('applies data-theme attribute to document', async () => {
    render(
      <ThemeProvider>
        <TestComponent />
      </ThemeProvider>
    );
    const button = screen.getByTestId('toggle-btn');

    await waitFor(() => {
      expect(document.documentElement.getAttribute('data-theme')).toBe('light');
    });

    fireEvent.click(button);

    await waitFor(() => {
      expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    });
  });

  test('throws error when useTheme is used outside ThemeProvider', () => {
    const TestComponentWithoutProvider = () => {
      useTheme();
      return null;
    };

    // Suppress console.error for this test
    const spy = jest.spyOn(console, 'error').mockImplementation(() => {});

    expect(() => {
      render(<TestComponentWithoutProvider />);
    }).toThrow('useTheme must be used within a ThemeProvider');

    spy.mockRestore();
  });
});
