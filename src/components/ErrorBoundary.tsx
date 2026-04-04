import React, { Component, ErrorInfo, ReactNode } from 'react';

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

/**
 * Top-level error boundary that catches React render crashes and shows
 * a user-friendly fallback instead of a blank screen.
 */
class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    // Log to console so monitoring tools can pick it up
    console.error('ErrorBoundary caught an error:', error, errorInfo);
  }

  handleRetry = (): void => {
    this.setState({ hasError: false, error: null });
  };

  render(): ReactNode {
    if (this.state.hasError) {
      return (
        <div role="alert" style={{
          padding: '40px',
          textAlign: 'center',
          fontFamily: 'sans-serif',
        }}>
          <h2>Something went wrong</h2>
          <p style={{ color: '#666', marginBottom: '20px' }}>
            An unexpected error occurred. Please try again.
          </p>
          {this.state.error && (
            <details style={{ marginBottom: '20px', color: '#999' }}>
              <summary>Error details</summary>
              <pre style={{ textAlign: 'left', whiteSpace: 'pre-wrap' }}>
                {this.state.error.message}
              </pre>
            </details>
          )}
          <button
            onClick={this.handleRetry}
            style={{
              padding: '10px 24px',
              fontSize: '16px',
              cursor: 'pointer',
              borderRadius: '4px',
              border: '1px solid #ccc',
              backgroundColor: '#f0f0f0',
            }}
          >
            Try Again
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
