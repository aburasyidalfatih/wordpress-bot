import { useEffect, useState } from 'react';

function prefersDark() {
  const saved = localStorage.getItem('theme');
  return saved === 'dark' || (!saved && window.matchMedia('(prefers-color-scheme: dark)').matches);
}

/** Dark-mode flag persisted in localStorage and applied to <html class="dark">. */
export function useDarkMode() {
  const [isDarkMode, setIsDarkMode] = useState(prefersDark);

  useEffect(() => {
    document.documentElement.classList.toggle('dark', isDarkMode);
    localStorage.setItem('theme', isDarkMode ? 'dark' : 'light');
  }, [isDarkMode]);

  const toggleDarkMode = () => setIsDarkMode(dark => !dark);
  return { isDarkMode, toggleDarkMode };
}
