'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Bot, ChevronDown, Home, Settings2 } from 'lucide-react';

const standard = [
  ['/full-scan', 'Full mailbox scan'],
  ['/biggest', 'Biggest mails'],
  ['/senders', 'Top senders'],
  ['/sent-mail', 'Sent mail'],
  ['/newsletters', 'Newsletters'],
  ['/archive', 'Archive storage'],
  ['/automation', 'Automation Center'],
  ['/control-center', 'Control Center'],
  ['/mailbox-health', 'Mailbox Health'],
] as const;
const intelligence = [
  ['/action-inbox', 'Action Inbox'],
  ['/smart-search', 'Smart Search'],
  ['/ai-cleanup', 'AI Cleanup'],
  ['/documents', 'Documents & lifecycle'],
  ['/relationships', 'Companies & relationships'],
  ['/promotions', 'Promotions & Clutter'],
  ['/security', 'Spam & phishing'],
  ['/filing-plan', 'AI Filing plan'],
  ['/ai-quality', 'AI Quality Center'],
] as const;

export function GlobalNav() {
  const [path, setPath] = useState('');
  useEffect(() => {
    const timer = window.setTimeout(() => setPath(window.location.pathname), 0);
    return () => window.clearTimeout(timer);
  }, []);
  if (!path || path === '/') return null;
  return (
    <nav
      className="sticky top-0 z-40 flex h-14 items-center gap-2 border-b bg-background/95 px-4 pr-28 backdrop-blur"
      aria-label="Global navigation"
    >
      <Link
        href="/"
        className="inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold hover:bg-card"
      >
        <Home size={16} />
        Overview
      </Link>
      <NavGroup
        icon={<Settings2 size={16} />}
        label="Standard"
        items={standard}
        path={path}
      />
      <NavGroup
        icon={<Bot size={16} />}
        label="AI functions"
        items={intelligence}
        path={path}
      />
    </nav>
  );
}

function NavGroup({
  icon,
  label,
  items,
  path,
}: {
  icon: React.ReactNode;
  label: string;
  items: ReadonlyArray<readonly [string, string]>;
  path: string;
}) {
  return (
    <details className="group relative">
      <summary className="flex cursor-pointer list-none items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold hover:bg-card">
        {icon}
        {label}
        <ChevronDown
          size={14}
          className="transition-transform group-open:rotate-180"
        />
      </summary>
      <div className="absolute left-0 top-full mt-1 min-w-64 rounded-xl border bg-popover p-2 shadow-xl">
        {items.map(([href, text]) => (
          <Link
            key={href}
            href={href}
            className={`block rounded-lg px-3 py-2 text-sm hover:bg-accent ${path === href ? 'bg-accent font-semibold' : ''}`}
          >
            {text}
          </Link>
        ))}
      </div>
    </details>
  );
}
