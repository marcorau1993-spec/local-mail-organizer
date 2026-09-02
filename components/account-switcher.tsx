'use client';

import { useCallback, useEffect, useState } from 'react';
import { Mail } from 'lucide-react';

const API_URL = 'http://127.0.0.1:8765';
export type MailAccount = {
  id: string;
  provider: string;
  username: string;
  connected_at: string;
};

export function useAccountSelection() {
  const [accounts, setAccounts] = useState<MailAccount[]>([]);
  const [accountId, setAccountIdState] = useState('');
  const [loading, setLoading] = useState(true);
  const setAccountId = useCallback((value: string) => {
    setAccountIdState(value);
    if (value) window.localStorage.setItem('mail-organizer-account', value);
  }, []);
  useEffect(() => {
    const timer = window.setTimeout(
      () =>
        void (async () => {
          try {
            const response = await fetch(`${API_URL}/api/accounts`, {
              cache: 'no-store',
            });
            const payload = (await response.json()) as {
              accounts: MailAccount[];
            };
            setAccounts(payload.accounts);
            const saved = window.localStorage.getItem('mail-organizer-account');
            const selected = payload.accounts.some((item) => item.id === saved)
              ? saved
              : (payload.accounts[0]?.id ?? '');
            setAccountIdState(selected ?? '');
          } finally {
            setLoading(false);
          }
        })(),
      0,
    );
    return () => window.clearTimeout(timer);
  }, []);
  return { accounts, accountId, setAccountId, loading };
}

export function AccountSwitcher({
  accounts,
  accountId,
  onChange,
  className = '',
}: {
  accounts: MailAccount[];
  accountId: string;
  onChange: (value: string) => void;
  className?: string;
}) {
  return (
    <label
      className={`inline-flex items-center gap-2 rounded-xl border bg-card px-3 py-2 ${className}`}
    >
      <Mail size={16} className="text-primary" />
      <span className="text-xs font-semibold text-muted-foreground">
        Mailbox
      </span>
      <select
        value={accountId}
        onChange={(event) => onChange(event.target.value)}
        className="max-w-64 bg-transparent text-sm font-semibold outline-none"
        aria-label="Active mailbox"
      >
        {accounts.map((account) => (
          <option key={account.id} value={account.id}>
            {account.username} · {account.provider}
          </option>
        ))}
      </select>
    </label>
  );
}
