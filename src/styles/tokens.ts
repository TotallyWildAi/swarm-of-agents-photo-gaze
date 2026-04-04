/**
 * Design System Tokens
 * Centralized definitions for spacing, typography, and color palette
 */

// Spacing scale (4px base unit)
export const spacing = {
  xxs: '4px',   // 1x
  xs: '8px',    // 2x
  sm: '12px',   // 3x
  md: '16px',   // 4x
  lg: '20px',   // 5x
  xl: '24px',   // 6x
  xxl: '32px',  // 8x
} as const;

// Typography
export const typography = {
  fontFamily: {
    base: '-apple-system, BlinkMacSystemFont, "Segoe UI", "Roboto", "Oxygen", "Ubuntu", "Cantarell", "Fira Sans", "Droid Sans", "Helvetica Neue", sans-serif',
    mono: '"SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace',
  },
  fontSize: {
    xs: '12px',
    sm: '14px',
    base: '16px',
    lg: '18px',
    xl: '20px',
    xxl: '24px',
  },
  fontWeight: {
    normal: 400,
    medium: 500,
    bold: 700,
  },
  lineHeight: {
    tight: 1.2,
    normal: 1.5,
    relaxed: 1.75,
  },
} as const;

// Color palette - limited and harmonious
export const colors = {
  // Primary (cyan/blue)
  primary: '#61dafb',
  primaryDark: '#4db8d8',
  primaryLight: '#e0f7ff',

  // Success (green)
  success: '#4caf50',
  successLight: '#e8f5e9',

  // Warning (orange)
  warning: '#ff9800',
  warningLight: '#fff3e0',

  // Error (red)
  error: '#d32f2f',
  errorLight: '#ffebee',

  // Neutral (grayscale)
  neutralDark: '#282c34',
  neutralMedium: '#999999',
  neutralLight: '#f5f5f5',
  white: '#ffffff',
} as const;

// Border radius
export const borderRadius = {
  sm: '4px',
  md: '8px',
  lg: '12px',
  full: '9999px',
} as const;

// Responsive breakpoints
export const breakpoints = {
  mobile: '320px',
  tablet: '768px',
  desktop: '1024px',
  wide: '1440px',
} as const;

// Shadows
export const shadows = {
  sm: '0 1px 2px rgba(0, 0, 0, 0.05)',
  md: '0 4px 6px rgba(0, 0, 0, 0.1)',
  lg: '0 10px 15px rgba(0, 0, 0, 0.1)',
  xl: '0 20px 25px rgba(0, 0, 0, 0.1)',
} as const;
