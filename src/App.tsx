import React from 'react';
import { ThemeProvider } from './context/ThemeContext';
import { ThemeToggle } from './components/ThemeToggle';
import './styles/theme.css';
import './App.css';

function App() {
  return (
    <ThemeProvider>
      <div className="app">
        <header className="app-header">
          <h1>Theme Toggle Demo</h1>
          <ThemeToggle />
        </header>
        <main className="app-main">
          <p>Click the theme toggle button to switch between light and dark modes.</p>
          <p>Your preference will be saved and restored on your next visit.</p>
        </main>
      </div>
    </ThemeProvider>
  );
}

export default App;
