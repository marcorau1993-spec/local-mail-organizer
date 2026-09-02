'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import {
  ArrowLeft,
  Download,
  History,
  Plus,
  RefreshCw,
  ShieldCheck,
  Trash2,
} from 'lucide-react';
import {
  AccountSwitcher,
  useAccountSelection,
} from '@/components/account-switcher';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

const API_URL = 'http://127.0.0.1:8765';
type Rule = { id: string; kind: string; value: string; enabled: number };
type Operation = {
  id: string;
  action: string;
  folder: string;
  uid: string;
  destination?: string;
  status: string;
  undo_status?: string;
  created_at: string;
};
type Preferences = {
  paused: number;
  learning_mode: number;
  schedule_minutes: number;
  max_actions: number;
  notify_errors: number;
};
type InsightRow = {
  label?: string;
  subject?: string;
  sender?: string;
  messages?: number;
  bytes?: number;
  copies?: number;
};
type MailResult = {
  folder: string;
  uid: string;
  subject: string;
  sender: string;
  size_bytes: number;
  internal_date?: string;
};
type RetentionPolicy = {
  id: string;
  category: string;
  action: 'archive_review' | 'trash_review';
  age_days: number;
};
type RetentionPreview = {
  policies: RetentionPolicy[];
  groups: number;
  messages: number;
  bytes: number;
  dry_run: boolean;
};
type FilingPreview = {
  matched_rules: number;
  groups: number;
  messages: number;
  bytes: number;
  dry_run: boolean;
};

function formatBytes(value = 0) {
  if (value < 1_048_576) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1_073_741_824) return `${(value / 1_048_576).toFixed(1)} MB`;
  return `${(value / 1_073_741_824).toFixed(1)} GB`;
}

export default function ControlCenterPage() {
  const { accounts, accountId, setAccountId } = useAccountSelection();
  const [rules, setRules] = useState<Rule[]>([]);
  const [operations, setOperations] = useState<Operation[]>([]);
  const [preferences, setPreferences] = useState<Preferences | null>(null);
  const [insights, setInsights] = useState<{
    by_sender: InsightRow[];
    by_folder: InsightRow[];
    by_year: InsightRow[];
    duplicates: InsightRow[];
  } | null>(null);
  const [kind, setKind] = useState('sender');
  const [value, setValue] = useState('');
  const [query, setQuery] = useState('');
  const [mailQuery, setMailQuery] = useState('');
  const [mailResults, setMailResults] = useState<MailResult[]>([]);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [retention, setRetention] = useState<RetentionPreview | null>(null);
  const [filingPreview, setFilingPreview] = useState<FilingPreview | null>(
    null,
  );
  const [retentionCategory, setRetentionCategory] = useState('notification');
  const [retentionAction, setRetentionAction] = useState<
    'archive_review' | 'trash_review'
  >('archive_review');
  const [retentionDays, setRetentionDays] = useState(730);

  const load = useCallback(async () => {
    if (!accountId) return;
    const scope = `account_id=${encodeURIComponent(accountId)}`;
    const [safetyResponse, insightResponse, retentionResponse, filingResponse] =
      await Promise.all([
        fetch(`${API_URL}/api/safety-center?${scope}`, { cache: 'no-store' }),
        fetch(`${API_URL}/api/insights?${scope}`, { cache: 'no-store' }),
        fetch(`${API_URL}/api/retention/preview?${scope}`, {
          cache: 'no-store',
        }),
        fetch(`${API_URL}/api/filing-rules/preview?${scope}`, {
          cache: 'no-store',
        }),
      ]);
    if (
      !safetyResponse.ok ||
      !insightResponse.ok ||
      !retentionResponse.ok ||
      !filingResponse.ok
    )
      throw new Error('Control Center is unavailable');
    const safety = (await safetyResponse.json()) as {
      rules: Rule[];
      operations: Operation[];
      preferences: Preferences;
    };
    setRules(safety.rules);
    setOperations(safety.operations);
    setPreferences(safety.preferences);
    setInsights(await insightResponse.json());
    setRetention(await retentionResponse.json());
    setFilingPreview(await filingResponse.json());
  }, [accountId]);

  useEffect(() => {
    const timer = window.setTimeout(
      () => void load().catch((e) => setError(e.message)),
      0,
    );
    return () => window.clearTimeout(timer);
  }, [load]);
  const visibleOperations = useMemo(
    () =>
      operations.filter((item) =>
        `${item.action} ${item.folder} ${item.destination ?? ''} ${item.status}`
          .toLowerCase()
          .includes(query.toLowerCase()),
      ),
    [operations, query],
  );

  async function addRule() {
    if (!value.trim()) return;
    const response = await fetch(`${API_URL}/api/protection-rules`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ account_id: accountId, kind, value }),
    });
    if (!response.ok) {
      setError('Could not save protection rule');
      return;
    }
    setValue('');
    setMessage('Protection rule enabled');
    await load();
  }
  async function searchMail() {
    const response = await fetch(
      `${API_URL}/api/search?account_id=${encodeURIComponent(accountId)}&q=${encodeURIComponent(mailQuery)}`,
      { cache: 'no-store' },
    );
    if (!response.ok) {
      setError('Mailbox search failed');
      return;
    }
    setMailResults(((await response.json()) as { items: MailResult[] }).items);
  }
  async function removeRule(id: string) {
    await fetch(
      `${API_URL}/api/protection-rules/${id}?account_id=${encodeURIComponent(accountId)}`,
      { method: 'DELETE' },
    );
    await load();
  }
  async function savePreferences(next: Preferences) {
    setPreferences(next);
    const response = await fetch(`${API_URL}/api/account-preferences`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        account_id: accountId,
        paused: Boolean(next.paused),
        learning_mode: Boolean(next.learning_mode),
        schedule_minutes: Number(next.schedule_minutes),
        max_actions: Number(next.max_actions),
        notify_errors: Boolean(next.notify_errors),
      }),
    });
    if (!response.ok) setError('Could not save automation preferences');
    else setMessage('Automation preferences saved');
  }
  async function undo(operationId: string) {
    if (!window.confirm('Move this message back to its original folder?'))
      return;
    const response = await fetch(`${API_URL}/api/operations/undo`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        account_id: accountId,
        operation_id: operationId,
      }),
    });
    const payload = (await response.json()) as { detail?: string };
    if (!response.ok) setError(payload.detail || 'Undo stopped safely');
    else {
      setMessage('Operation undone');
      await load();
    }
  }
  async function saveRetentionPolicy() {
    if (!accountId) return;
    const response = await fetch(`${API_URL}/api/retention/policies`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        account_id: accountId,
        category: retentionCategory,
        action: retentionAction,
        age_days: retentionDays,
      }),
    });
    const payload = (await response.json()) as RetentionPreview & {
      detail?: string;
    };
    if (!response.ok) {
      setError(payload.detail || 'Could not save retention policy');
      return;
    }
    setRetention(payload);
    setMessage(
      'Retention policy saved. Preview only — no messages were changed.',
    );
  }
  async function removeRetentionPolicy(id: string) {
    const response = await fetch(
      `${API_URL}/api/retention/policies/${id}?account_id=${encodeURIComponent(accountId)}`,
      { method: 'DELETE' },
    );
    if (!response.ok) {
      setError('Could not remove retention policy');
      return;
    }
    setRetention((await response.json()) as RetentionPreview);
  }
  async function exportConfig() {
    const password = window.prompt(
      'Choose a password for the encrypted backup (minimum 8 characters).',
    );
    if (!password || password.length < 8) {
      setError('Backup cancelled: password must contain at least 8 characters');
      return;
    }
    const payload = await (
      await fetch(
        `${API_URL}/api/config/export?account_id=${encodeURIComponent(accountId)}`,
      )
    ).json();
    const encrypted = await encryptBackup(JSON.stringify(payload), password);
    const link = document.createElement('a');
    link.href = URL.createObjectURL(
      new Blob([JSON.stringify(encrypted, null, 2)], {
        type: 'application/json',
      }),
    );
    link.download = 'mail-organizer-config.encrypted.json';
    link.click();
    URL.revokeObjectURL(link.href);
  }

  async function importConfig(file: File) {
    const password = window.prompt('Enter the configuration backup password.');
    if (!password) return;
    try {
      const envelope = JSON.parse(await file.text()) as EncryptedBackup;
      const decoded = JSON.parse(await decryptBackup(envelope, password)) as {
        protection_rules?: Rule[];
        preferences?: Preferences;
      };
      const response = await fetch(`${API_URL}/api/config/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          account_id: accountId,
          protection_rules: decoded.protection_rules ?? [],
          preferences: decoded.preferences ?? {},
        }),
      });
      if (!response.ok) throw new Error('Import rejected');
      setMessage('Encrypted configuration restored without credentials');
      await load();
    } catch {
      setError('Could not decrypt or import this backup');
    }
  }

  return (
    <main className="min-h-screen bg-background px-5 py-8 text-foreground">
      <div className="mx-auto max-w-7xl">
        <Link
          href="/"
          className="inline-flex items-center gap-2 text-sm text-muted-foreground"
        >
          <ArrowLeft size={16} />
          Overview
        </Link>
        <div className="mt-7 flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="eyebrow">Mailbox operations</p>
            <h1 className="mt-2 text-3xl font-semibold">Control Center</h1>
            <p className="mt-2 text-sm text-muted-foreground">
              Safety rules, learning mode, activity, recovery, storage insights,
              and anonymous configuration backup.
            </p>
            <AccountSwitcher
              accounts={accounts}
              accountId={accountId}
              onChange={setAccountId}
              className="mt-4"
            />
          </div>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => void exportConfig()}>
              <Download /> Encrypted backup
            </Button>
            <label className="inline-flex cursor-pointer items-center rounded-lg border px-3 text-sm font-semibold">
              Restore
              <input
                type="file"
                accept="application/json"
                className="sr-only"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) void importConfig(file);
                }}
              />
            </label>
          </div>
        </div>
        {error && (
          <div className="mt-5 rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
            {error}
          </div>
        )}
        {message && (
          <div className="mt-5 rounded-xl border border-safe/30 bg-safe-soft p-3 text-sm text-safe">
            {message}
          </div>
        )}
        <div className="mt-6 grid gap-5 lg:grid-cols-2">
          <section className="panel">
            <h2 className="flex items-center gap-2 text-lg font-semibold">
              <ShieldCheck size={19} />
              Protection rules
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Matching messages are blocked before any move or deletion.
            </p>
            <div className="mt-4 flex gap-2">
              <select
                className="rounded-lg border bg-background px-3 text-sm"
                value={kind}
                onChange={(e) => setKind(e.target.value)}
              >
                <option value="sender">Sender</option>
                <option value="domain">Domain</option>
                <option value="folder">Folder</option>
                <option value="subject">Subject contains</option>
              </select>
              <Input
                value={value}
                onChange={(e) => setValue(e.target.value)}
                placeholder="Value to always protect"
              />
              <Button onClick={() => void addRule()}>
                <Plus />
              </Button>
            </div>
            <div className="mt-4 space-y-2">
              {rules.map((rule) => (
                <div
                  key={rule.id}
                  className="flex items-center justify-between rounded-lg border p-3 text-sm"
                >
                  <span>
                    <b>{rule.kind}</b> · {rule.value}
                  </span>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => void removeRule(rule.id)}
                  >
                    <Trash2 size={15} />
                  </Button>
                </div>
              ))}
            </div>
          </section>
          <section className="panel">
            <h2 className="text-lg font-semibold">Automation & learning</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Learning mode proposes actions but never executes them
              automatically.
            </p>
            {preferences && (
              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={Boolean(preferences.learning_mode)}
                    onChange={(e) =>
                      void savePreferences({
                        ...preferences,
                        learning_mode: Number(e.target.checked),
                      })
                    }
                  />
                  Learning mode
                </label>
                <label className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={Boolean(preferences.paused)}
                    onChange={(e) =>
                      void savePreferences({
                        ...preferences,
                        paused: Number(e.target.checked),
                      })
                    }
                  />
                  Pause account
                </label>
                <label className="text-sm" htmlFor="schedule-minutes">
                  Interval (minutes)
                  <Input
                    id="schedule-minutes"
                    type="number"
                    value={preferences.schedule_minutes}
                    onChange={(e) =>
                      setPreferences({
                        ...preferences,
                        schedule_minutes: Number(e.target.value),
                      })
                    }
                    onBlur={() => void savePreferences(preferences)}
                  />
                </label>
                <label className="text-sm" htmlFor="max-actions">
                  Maximum actions/run
                  <Input
                    id="max-actions"
                    type="number"
                    value={preferences.max_actions}
                    onChange={(e) =>
                      setPreferences({
                        ...preferences,
                        max_actions: Number(e.target.value),
                      })
                    }
                    onBlur={() => void savePreferences(preferences)}
                  />
                </label>
              </div>
            )}
          </section>
        </div>
        <div className="mt-5 grid gap-5 lg:grid-cols-2">
          <section className="panel">
            <h2 className="text-lg font-semibold">
              Retention policy simulator
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Save account-specific review policies and see their effect before
              anything changes.
            </p>
            <div className="mt-4 grid gap-2 sm:grid-cols-[1fr_1fr_110px_auto]">
              <select
                className="rounded-lg border bg-background px-3 text-sm"
                value={retentionCategory}
                onChange={(event) => setRetentionCategory(event.target.value)}
              >
                {[
                  'notification',
                  'promotion',
                  'system',
                  'other',
                  'order',
                  'travel',
                  'support',
                ].map((category) => (
                  <option key={category}>{category}</option>
                ))}
              </select>
              <select
                className="rounded-lg border bg-background px-3 text-sm"
                value={retentionAction}
                onChange={(event) =>
                  setRetentionAction(
                    event.target.value as 'archive_review' | 'trash_review',
                  )
                }
              >
                <option value="archive_review">Archive review</option>
                <option value="trash_review">Trash review</option>
              </select>
              <Input
                type="number"
                min={30}
                max={7300}
                value={retentionDays}
                onChange={(event) =>
                  setRetentionDays(Number(event.target.value))
                }
                aria-label="Age in days"
              />
              <Button onClick={() => void saveRetentionPolicy()}>Add</Button>
            </div>
            <p className="mt-3 text-sm font-medium">
              Dry run: {(retention?.messages ?? 0).toLocaleString()} messages in{' '}
              {retention?.groups ?? 0} groups ·{' '}
              {formatBytes(retention?.bytes ?? 0)}
            </p>
            <div className="mt-3 space-y-2">
              {retention?.policies.map((policy) => (
                <div
                  key={policy.id}
                  className="flex items-center justify-between rounded-lg border p-3 text-sm"
                >
                  <span>
                    <b>{policy.category}</b> ·{' '}
                    {policy.action.replaceAll('_', ' ')} after {policy.age_days}{' '}
                    days
                  </span>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => void removeRetentionPolicy(policy.id)}
                  >
                    <Trash2 size={14} />
                  </Button>
                </div>
              ))}
            </div>
          </section>
          <section className="panel">
            <h2 className="text-lg font-semibold">Filing-rule dry run</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Current active rules are simulated against the latest Qwen
              analysis without moving mail.
            </p>
            <div className="mt-5 grid grid-cols-2 gap-3">
              <div className="rounded-lg border p-4">
                <div className="text-2xl font-semibold">
                  {filingPreview?.matched_rules ?? 0}
                </div>
                <div className="text-xs text-muted-foreground">
                  active categories
                </div>
              </div>
              <div className="rounded-lg border p-4">
                <div className="text-2xl font-semibold">
                  {(filingPreview?.messages ?? 0).toLocaleString()}
                </div>
                <div className="text-xs text-muted-foreground">
                  messages matched
                </div>
              </div>
              <div className="rounded-lg border p-4">
                <div className="text-2xl font-semibold">
                  {filingPreview?.groups ?? 0}
                </div>
                <div className="text-xs text-muted-foreground">
                  folder proposals
                </div>
              </div>
              <div className="rounded-lg border p-4">
                <div className="text-2xl font-semibold">
                  {formatBytes(filingPreview?.bytes ?? 0)}
                </div>
                <div className="text-xs text-muted-foreground">
                  mail covered
                </div>
              </div>
            </div>
          </section>
        </div>
        <section className="panel mt-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="flex items-center gap-2 text-lg font-semibold">
                <History size={19} />
                Activity & Undo
              </h2>
              <p className="text-sm text-muted-foreground">
                Every mailbox mutation is account-scoped and auditable.
              </p>
            </div>
            <Input
              className="max-w-sm"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Filter activity…"
            />
          </div>
          <div className="mt-4 overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b">
                  <th className="p-2">Time</th>
                  <th>Action</th>
                  <th>From</th>
                  <th>To</th>
                  <th>Status</th>
                  <th aria-label="Actions"></th>
                </tr>
              </thead>
              <tbody>
                {visibleOperations.map((item) => (
                  <tr key={item.id} className="border-b">
                    <td className="p-2">
                      {new Date(item.created_at).toLocaleString()}
                    </td>
                    <td>{item.action}</td>
                    <td>{item.folder}</td>
                    <td>{item.destination || '—'}</td>
                    <td>
                      {item.undo_status === 'completed'
                        ? 'undone'
                        : item.status}
                    </td>
                    <td>
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={item.undo_status === 'completed'}
                        onClick={() => void undo(item.id)}
                      >
                        <RefreshCw size={14} />
                        Undo
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
        <section className="panel mt-5">
          <h2 className="text-lg font-semibold">Local mailbox search</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Search indexed subject and sender metadata without contacting a
            hosted service.
          </p>
          <div className="mt-4 flex gap-2">
            <Input
              value={mailQuery}
              onChange={(event) => setMailQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') void searchMail();
              }}
              placeholder="Subject, sender, or domain…"
            />
            <Button onClick={() => void searchMail()}>Search</Button>
          </div>
          <div className="mt-4 max-h-80 space-y-2 overflow-auto">
            {mailResults.map((item) => (
              <div
                key={`${item.folder}:${item.uid}`}
                className="grid gap-1 rounded-lg border p-3 text-sm sm:grid-cols-[1fr_180px_100px]"
              >
                <div>
                  <b>{item.subject || '(no subject)'}</b>
                  <div className="text-xs text-muted-foreground">
                    {item.sender}
                  </div>
                </div>
                <span>{item.folder}</span>
                <span>{formatBytes(item.size_bytes)}</span>
              </div>
            ))}
          </div>
        </section>
        <section className="panel mt-5">
          <h2 className="text-lg font-semibold">
            Mailbox insights & duplicates
          </h2>
          <div className="mt-4 grid gap-5 md:grid-cols-4">
            <Insight title="Largest senders" rows={insights?.by_sender} />
            <Insight title="Folder sizes" rows={insights?.by_folder} />
            <Insight title="By year" rows={insights?.by_year} />
            <Insight title="Duplicate groups" rows={insights?.duplicates} />
          </div>
        </section>
      </div>
    </main>
  );
}

function Insight({ title, rows = [] }: { title: string; rows?: InsightRow[] }) {
  return (
    <div>
      <h3 className="font-semibold">{title}</h3>
      <div className="mt-2 space-y-2">
        {rows.slice(0, 10).map((row, index) => (
          <div
            key={`${row.label ?? row.subject}-${index}`}
            className="rounded-lg border p-2 text-xs"
          >
            <div className="truncate font-medium">
              {row.label ?? row.subject ?? 'Unknown'}
            </div>
            <div className="text-muted-foreground">
              {row.copies
                ? `${row.copies} copies`
                : `${row.messages ?? 0} mails`}{' '}
              ·{' '}
              {formatBytes(
                row.bytes ?? ((row.copies ?? 1) - 1) * (row.bytes ?? 0),
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

type EncryptedBackup = {
  format: 'local-mail-organizer-encrypted-v1';
  salt: string;
  iv: string;
  data: string;
};
const toBase64 = (value: Uint8Array) => btoa(String.fromCharCode(...value));
const fromBase64 = (value: string) =>
  Uint8Array.from(atob(value), (character) => character.charCodeAt(0));

async function backupKey(password: string, salt: Uint8Array) {
  const material = await crypto.subtle.importKey(
    'raw',
    new TextEncoder().encode(password),
    'PBKDF2',
    false,
    ['deriveKey'],
  );
  return crypto.subtle.deriveKey(
    {
      name: 'PBKDF2',
      salt: new Uint8Array(salt).buffer,
      iterations: 250000,
      hash: 'SHA-256',
    },
    material,
    { name: 'AES-GCM', length: 256 },
    false,
    ['encrypt', 'decrypt'],
  );
}

async function encryptBackup(
  content: string,
  password: string,
): Promise<EncryptedBackup> {
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const data = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv: new Uint8Array(iv).buffer },
    await backupKey(password, salt),
    new TextEncoder().encode(content),
  );
  return {
    format: 'local-mail-organizer-encrypted-v1',
    salt: toBase64(salt),
    iv: toBase64(iv),
    data: toBase64(new Uint8Array(data)),
  };
}

async function decryptBackup(envelope: EncryptedBackup, password: string) {
  if (envelope.format !== 'local-mail-organizer-encrypted-v1')
    throw new Error('Unsupported backup');
  const salt = fromBase64(envelope.salt);
  const iv = fromBase64(envelope.iv);
  const data = await crypto.subtle.decrypt(
    { name: 'AES-GCM', iv: new Uint8Array(iv).buffer },
    await backupKey(password, salt),
    new Uint8Array(fromBase64(envelope.data)).buffer,
  );
  return new TextDecoder().decode(data);
}
