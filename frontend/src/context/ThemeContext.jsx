import React, { createContext, useContext, useState, useEffect } from 'react';

const ThemeContext = createContext();

export function ThemeProvider({ children }) {
  const [theme, setTheme] = useState('dark');

  useEffect(() => {
    const savedSettings = localStorage.getItem('appSettings');
    if (savedSettings) {
      const parsed = JSON.parse(savedSettings);
      if (parsed.theme) {
        setTheme(parsed.theme);
      }
    }
  }, []);
  // Keep the document root in sync so CSS variables apply everywhere (body, :root, etc.)
  useEffect(() => {
    // Remove any existing theme- classes then add the current one
    document.documentElement.classList.remove('theme-dark', 'theme-light', 'theme-cyberpunk', 'theme-matrix');
    document.documentElement.classList.add(`theme-${theme}`);
  }, [theme]);

  const changeTheme = (newTheme) => {
    console.log('Theme change requested:', newTheme);
    setTheme(newTheme);
    // Update localStorage
    const savedSettings = localStorage.getItem('appSettings');
    let settings = {};
    if (savedSettings) {
      settings = JSON.parse(savedSettings);
    }
    settings.theme = newTheme;
    localStorage.setItem('appSettings', JSON.stringify(settings));
  };

  return (
    <ThemeContext.Provider value={{ theme, changeTheme }}>
      <div className={`theme-${theme} min-h-screen bg-background text-primary transition-colors duration-300`}>
        {children}
      </div>
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  return useContext(ThemeContext);
}
