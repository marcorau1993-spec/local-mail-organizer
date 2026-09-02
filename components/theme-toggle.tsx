'use client';

import { useEffect, useState } from 'react';
import { Monitor, Moon, Sun } from 'lucide-react';

type Theme = 'system' | 'light' | 'dark';

function applyTheme(theme: Theme) {
  const dark =
    theme === 'dark' ||
    (theme === 'system' &&
      window.matchMedia('(prefers-color-scheme: dark)').matches);
  document.documentElement.classList.toggle('dark', dark);
  document.documentElement.style.colorScheme = dark ? 'dark' : 'light';
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>('system');
  useEffect(() => {
    const saved =
      (window.localStorage.getItem('mail-organizer-theme') as Theme | null) ??
      'system';
    const timer = window.setTimeout(() => {
      setTheme(saved);
      applyTheme(saved);
    }, 0);
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    const update = () => saved === 'system' && applyTheme('system');
    media.addEventListener('change', update);
    return () => {
      window.clearTimeout(timer);
      media.removeEventListener('change', update);
    };
  }, []);
  const cycle = () => {
    const next: Theme =
      theme === 'system' ? 'dark' : theme === 'dark' ? 'light' : 'system';
    setTheme(next);
    window.localStorage.setItem('mail-organizer-theme', next);
    applyTheme(next);
  };
  const Icon = theme === 'dark' ? Moon : theme === 'light' ? Sun : Monitor;
  return (
    <button
      type="button"
      onClick={cycle}
      className="fixed right-4 top-4 z-50 inline-flex items-center gap-2 rounded-xl border bg-card px-3 py-2 text-xs font-semibold shadow-sm"
      title={`Theme: ${theme}. Click to change.`}
    >
      <Icon size={15} />
      <span className="hidden sm:inline">{theme}</span>
    </button>
  );
}
