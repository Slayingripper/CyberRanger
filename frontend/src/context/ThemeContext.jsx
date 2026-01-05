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

  const changeTheme = (newTheme) => {
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
