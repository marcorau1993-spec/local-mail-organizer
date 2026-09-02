'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { ArrowLeft, Sparkles, Trash2 } from 'lucide-react';
import {
  AccountSwitcher,
  useAccountSelection,
} from '@/components/account-switcher';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';

const API_URL = 'http://127.0.0.1:8765';
type Group = {
  id: string;
  sender: string;
  sender_domain: string;
  subject_pattern: string;
  message_count: number;
  total_bytes: number;
  category: string;
  confidence: number;
  reason: string;
  recommendation: string;
};
type Run = { id: string; status: string };
const formatBytes = (value: number) =>
  value >= 1_048_576
    ? `${(value / 1_048_576).toFixed(1)} MB`
    : `${(value / 1024).toFixed(1)} KB`;

export default function PromotionsPage() {
  const { accounts, accountId, setAccountId } = useAccountSelection();
  const [run, setRun] = useState<Run | null>(null);
  const [groups, setGroups] = useState<Group[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState('');
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const load = useCallback(async () => {
    if (!accountId) return;
    const response = await fetch(
      `${API_URL}/api/promotions?account_id=${encodeURIComponent(accountId)}`,
      { cache: 'no-store' },
    );
    if (!response.ok) throw new Error('Could not load promotional clutter');
    const payload = (await response.json()) as {
      run: Run | null;
      groups: Group[];
    };
    setRun(payload.run);
    setGroups(payload.groups);
    setSelected(new Set());
  }, [accountId]);
  useEffect(() => {
    const timer = window.setTimeout(
      () => void load().catch((e) => setError(e.message)),
      0,
    );
    return () => window.clearTimeout(timer);
  }, [load]);
  const visible = useMemo(
    () =>
      groups
        .filter((group) =>
          `${group.sender} ${group.sender_domain} ${group.subject_pattern} ${group.reason}`
            .toLowerCase()
            .includes(query.toLowerCase()),
        )
        .sort((a, b) => b.message_count - a.message_count),
    [groups, query],
  );
  const chosen = groups.filter((group) => selected.has(group.id));
  const mailCount = chosen.reduce((sum, group) => sum + group.message_count, 0);
  const byteCount = chosen.reduce((sum, group) => sum + group.total_bytes, 0);

  async function cleanup() {
    if (!run || !chosen.length) return;
    if (
      !window.confirm(
        `Move ${mailCount.toLocaleString()} selected campaign and provider-notice messages (${formatBytes(byteCount)}) from ${chosen.length} groups to Trash? Review security, account, and storage notices carefully before continuing.`,
      )
    )
      return;
    setPending(true);
    setError('');
    setMessage('');
    try {
      const totals = { moved: 0, attachments: 0, failed: 0 };
      for (let start = 0; start < chosen.length; start += 25) {
        const response = await fetch(`${API_URL}/api/ai-cleanup/actions`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            run_id: run.id,
            suggestion_ids: chosen
              .slice(start, start + 25)
              .map((group) => group.id),
            action: 'trash',
            confirmed: true,
          }),
        });
        const payload = (await response.json()) as {
          moved?: number;
          attachment_protected?: number;
          failed?: number;
          detail?: string;
        };
        if (!response.ok)
          throw new Error(
            payload.detail || `Cleanup stopped after ${totals.moved} messages`,
          );
        totals.moved += payload.moved ?? 0;
        totals.attachments += payload.attachment_protected ?? 0;
        totals.failed += payload.failed ?? 0;
        setMessage(
          `Processing groups ${Math.min(start + 25, chosen.length)} of ${chosen.length}…`,
        );
      }
      setMessage(
        `${totals.moved} messages moved to Trash · ${totals.attachments} attachments protected · ${totals.failed} failed`,
      );
      await load();
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : 'Cleanup stopped safely',
      );
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="min-h-screen bg-background px-5 py-8 text-foreground">
      <div className="mx-auto max-w-6xl">
        <Link
          href="/"
          className="inline-flex items-center gap-2 text-sm text-muted-foreground"
        >
          <ArrowLeft size={16} />
          Overview
        </Link>
        <div className="mt-7 flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="eyebrow">Qwen campaign intelligence</p>
            <h1 className="mt-2 text-3xl font-semibold">
              Promotions & Clutter
            </h1>
            <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
              Find recurring promotions, sweepstakes, provider campaigns, and
              WEB.DE/GMX account notices—even without an unsubscribe link.
            </p>
            <AccountSwitcher
              accounts={accounts}
              accountId={accountId}
              onChange={setAccountId}
              className="mt-4"
            />
          </div>
          <Link
            href="/ai-cleanup"
            className="text-sm font-semibold text-primary"
          >
            Run new Qwen analysis →
          </Link>
        </div>
        <section className="panel mt-6">
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="destructive"
              disabled={!selected.size || pending}
              onClick={() => void cleanup()}
            >
              <Trash2 />
              Move selected to Trash
            </Button>
            <Button
              variant="outline"
              disabled={!visible.length || pending}
              onClick={() =>
                setSelected(new Set(visible.map((group) => group.id)))
              }
            >
              Select all visible ({visible.length})
            </Button>
            <Button variant="ghost" onClick={() => setSelected(new Set())}>
              Clear
            </Button>
            <Input
              className="ml-auto max-w-sm"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Filter campaigns…"
            />
          </div>
          <p className="mt-3 text-xs text-muted-foreground">
            {selected.size} groups selected · {mailCount.toLocaleString()}{' '}
            messages · {formatBytes(byteCount)}
          </p>
        </section>
        {error && (
          <div className="mt-4 rounded-xl border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
            {error}
          </div>
        )}
        {message && (
          <div className="mt-4 rounded-xl border border-safe/30 bg-safe-soft p-3 text-sm text-safe">
            {message}
          </div>
        )}
        {!run && (
          <section className="panel mt-4 text-center">
            <Sparkles className="mx-auto" />
            <p className="mt-2 font-semibold">Run AI Cleanup first</p>
            <p className="text-sm text-muted-foreground">
              Qwen must analyze this mailbox before campaign groups are
              available.
            </p>
          </section>
        )}
        <div className="mt-4 grid gap-3">
          {visible.map((group) => (
            <article
              key={group.id}
              className="panel grid gap-3 sm:grid-cols-[36px_1fr_150px_120px]"
            >
              <Checkbox
                checked={selected.has(group.id)}
                disabled={pending}
                onCheckedChange={(checked) =>
                  setSelected((old) => {
                    const next = new Set(old);
                    if (checked) next.add(group.id);
                    else next.delete(group.id);
                    return next;
                  })
                }
              />
              <div className="min-w-0">
                <p className="truncate font-semibold">{group.sender}</p>
                <p className="truncate text-xs text-muted-foreground">
                  {group.subject_pattern || group.sender_domain}
                </p>
                <p className="mt-2 text-xs">Qwen: {group.reason}</p>
              </div>
              <div className="text-sm">
                <b>{group.message_count.toLocaleString()}</b> messages
                <br />
                <span className="text-xs text-muted-foreground">
                  {formatBytes(group.total_bytes)}
                </span>
              </div>
              <div className="text-sm">
                <b>{Math.round(group.confidence * 100)}%</b>
                <br />
                <span className="text-xs text-muted-foreground">
                  {group.category}
                </span>
              </div>
            </article>
          ))}
        </div>
      </div>
    </main>
  );
}
