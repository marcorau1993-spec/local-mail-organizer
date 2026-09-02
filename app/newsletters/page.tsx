'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { ArrowLeft, ExternalLink, Loader2, MailMinus } from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button, buttonVariants } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  filterAndSort,
  nextSort,
  SortableTableHead,
  TableFilterBar,
  type SortDirection,
} from '@/components/table-tools';
import {
  AccountSwitcher,
  useAccountSelection,
} from '@/components/account-switcher';

const API_URL = 'http://127.0.0.1:8765';
type Group = {
  job_id: string;
  sender: string;
  sender_domain: string;
  list_id: string;
  message_count: number;
  total_bytes: number;
  folder: string;
  uid: string;
};
type Method = 'automatic' | 'email' | 'manual' | 'unavailable';
const keyOf = (x: Group) => `${x.job_id}:${x.folder}:${x.uid}`;
function apiError(detail: unknown, fallback: string) {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) =>
        typeof item === 'object' && item !== null && 'msg' in item
          ? String(item.msg)
          : '',
      )
      .filter(Boolean);
    if (messages.length) return messages.join(' · ');
  }
  return fallback;
}

const wait = (milliseconds: number) =>
  new Promise((resolve) => window.setTimeout(resolve, milliseconds));

async function postBatch(batch: Group[], batchNumber: number) {
  let lastError = new Error(`Batch ${batchNumber} stopped safely`);
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    try {
      const response = await fetch(`${API_URL}/api/newsletters/unsubscribe`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          confirmed: true,
          items: batch.map(({ job_id, folder, uid }) => ({
            job_id,
            folder,
            uid,
          })),
        }),
      });
      const payload = (await response.json()) as {
        completed?: number;
        manual_review?: number;
        failed?: number;
        deleted_messages?: number;
        cleanup_failed?: number;
        results?: Array<{
          job_id: string;
          folder: string;
          uid: string;
          status: string;
        }>;
        detail?: unknown;
      };
      if (!response.ok) {
        throw new Error(
          apiError(payload.detail, `Batch ${batchNumber} stopped safely`),
        );
      }
      return payload;
    } catch (error) {
      lastError =
        error instanceof Error
          ? error
          : new Error('Connection to the local service failed');
      if (attempt < 3) await wait(attempt * 1500);
    }
  }
  throw lastError;
}

export default function NewslettersPage() {
  const { accounts, accountId, setAccountId } = useAccountSelection();
  const [groups, setGroups] = useState<Group[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [results, setResults] = useState<Record<string, string>>({});
  const [methods, setMethods] = useState<Record<string, Method>>({});
  const [pageUrls, setPageUrls] = useState<Record<string, string>>({});
  const [filter, setFilter] = useState<'all' | Method>('all');
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState<{ key: string; direction: SortDirection }>({
    key: 'messages',
    direction: 'desc',
  });
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const filteredGroups = groups.filter(
    (x) => filter === 'all' || methods[keyOf(x)] === filter,
  );
  const visibleGroups = filterAndSort(
    filteredGroups,
    query,
    (x) =>
      `${x.sender} ${x.sender_domain} ${x.list_id} ${methods[keyOf(x)] ?? ''} ${results[keyOf(x)] ?? ''}`,
    (x) =>
      sort.key === 'newsletter'
        ? x.sender
        : sort.key === 'status'
          ? results[keyOf(x)] || methods[keyOf(x)] || 'analyzing'
          : x.message_count,
    sort.direction,
  );
  const changeSort = (key: string) =>
    setSort((old) => nextSort(old.key, old.direction, key));
  const selectableGroups = visibleGroups.filter(
    (x) => methods[keyOf(x)] === 'automatic' || methods[keyOf(x)] === 'email',
  );
  async function load(id = accountId) {
    if (!id) {
      setGroups([]);
      return;
    }
    const scope = `account_id=${encodeURIComponent(id)}`;
    const r = await fetch(`${API_URL}/api/newsletters?${scope}`, {
      cache: 'no-store',
    });
    if (!r.ok) throw new Error('Could not load newsletters');
    setGroups(((await r.json()) as { groups: Group[] }).groups);
    const capabilityResponse = await fetch(
      `${API_URL}/api/newsletters/capabilities?${scope}`,
      { cache: 'no-store' },
    );
    if (!capabilityResponse.ok)
      throw new Error('Could not analyze unsubscribe methods');
    const capabilityPayload = (await capabilityResponse.json()) as {
      capabilities: Array<{
        job_id: string;
        folder: string;
        uid: string;
        method: Method;
        page_url?: string;
      }>;
    };
    setMethods(
      Object.fromEntries(
        capabilityPayload.capabilities.map((x) => [
          `${x.job_id}:${x.folder}:${x.uid}`,
          x.method,
        ]),
      ),
    );
    setPageUrls(
      Object.fromEntries(
        capabilityPayload.capabilities
          .filter((x) => x.page_url)
          .map((x) => [`${x.job_id}:${x.folder}:${x.uid}`, x.page_url!]),
      ),
    );
  }
  useEffect(() => {
    const t = window.setTimeout(() => {
      setSelected(new Set());
      void load(accountId).catch((e) => setError(e.message));
    }, 0);
    return () => window.clearTimeout(t);
  }, [accountId]);
  async function unsubscribe() {
    const chosen = groups.filter((x) => selected.has(keyOf(x)));
    if (!chosen.length) return;
    const messageCount = chosen.reduce(
      (sum, item) => sum + item.message_count,
      0,
    );
    if (
      !window.confirm(
        `Unsubscribe ${chosen.length} newsletter(s) and move ${messageCount} matching messages to Trash?`,
      )
    )
      return;
    setPending(true);
    setError('');
    setMessage('');
    try {
      const totals = {
        completed: 0,
        manual: 0,
        failed: 0,
        deleted: 0,
        cleanupFailed: 0,
      };
      const combinedResults: Record<string, string> = {};
      const batchSize = 25;
      for (let start = 0; start < chosen.length; start += batchSize) {
        const batch = chosen.slice(start, start + batchSize);
        setMessage(
          `Processing ${Math.min(start + batch.length, chosen.length)} of ${chosen.length} newsletters…`,
        );
        const p = await postBatch(batch, Math.floor(start / batchSize) + 1);
        totals.completed += p.completed ?? 0;
        totals.manual += p.manual_review ?? 0;
        totals.failed += p.failed ?? 0;
        totals.deleted += p.deleted_messages ?? 0;
        totals.cleanupFailed += p.cleanup_failed ?? 0;
        for (const item of p.results ?? [])
          combinedResults[`${item.job_id}:${item.folder}:${item.uid}`] =
            item.status;
        setResults({ ...combinedResults });
        setSelected((old) => {
          const next = new Set(old);
          for (const item of batch) next.delete(keyOf(item));
          return next;
        });
      }
      setMessage(
        `${totals.completed} unsubscribed · ${totals.deleted} messages moved to Trash · ${totals.manual} manual · ${totals.failed} endpoint failures · ${totals.cleanupFailed} cleanup failures`,
      );
      setSelected(new Set());
      await load();
    } catch (e) {
      setError(
        `${e instanceof Error ? e.message : 'Unsubscribe failed'}. Completed batches were saved; click again to resume the remaining selection.`,
      );
    } finally {
      setPending(false);
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
            <p className="eyebrow">Subscription control</p>
            <h1 className="mt-2 text-3xl font-semibold">Newsletters</h1>
            <AccountSwitcher
              accounts={accounts}
              accountId={accountId}
              onChange={setAccountId}
              className="mt-4"
            />
            <p className="mt-2 text-sm text-muted-foreground">
              Grouped senders from the latest full scan. Automatic requests use
              RFC 8058 with a safe email fallback.
            </p>
          </div>
          <span className="text-sm font-semibold">
            {selected.size} selected
          </span>
        </div>
        <div className="panel mt-6">
          <div className="flex flex-wrap gap-2">
            <Button
              disabled={!selected.size || pending}
              onClick={() => void unsubscribe()}
            >
              {pending ? <Loader2 className="animate-spin" /> : <MailMinus />}
              Unsubscribe + move mail to Trash
            </Button>
            <Button
              variant="outline"
              disabled={!selectableGroups.length || pending}
              onClick={() => setSelected(new Set(selectableGroups.map(keyOf)))}
            >
              Select all visible ({selectableGroups.length})
            </Button>
            <Button
              variant="ghost"
              disabled={!selected.size || pending}
              onClick={() => setSelected(new Set())}
            >
              Clear selection
            </Button>
            {(
              ['all', 'automatic', 'email', 'manual', 'unavailable'] as const
            ).map((value) => (
              <Button
                key={value}
                variant={filter === value ? 'secondary' : 'outline'}
                onClick={() => {
                  setFilter(value);
                  setSelected(new Set());
                }}
              >
                {value.replace('_', ' ')}
              </Button>
            ))}
          </div>
          <p className="mt-3 text-xs text-muted-foreground">
            Automatic retries temporary endpoint failures once, then uses an
            advertised unsubscribe email when available. Manual pages open
            individually after local HTTPS safety checks.
          </p>
        </div>
        {error && (
          <Alert variant="destructive" className="mt-4">
            <AlertTitle>Stopped safely</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {message && (
          <Alert className="mt-4">
            <AlertTitle>{pending ? 'In progress' : 'Completed'}</AlertTitle>
            <AlertDescription>{message}</AlertDescription>
          </Alert>
        )}
        <div className="panel mt-4 overflow-x-auto">
          <TableFilterBar
            value={query}
            onChange={setQuery}
            shown={visibleGroups.length}
            total={filteredGroups.length}
            placeholder="Filter newsletters, domains, or status…"
          />
          <Table className="table-fixed">
            <TableHeader>
              <TableRow>
                <TableHead className="w-10"></TableHead>
                <SortableTableHead
                  label="Newsletter"
                  sortKey="newsletter"
                  activeKey={sort.key}
                  direction={sort.direction}
                  onSort={changeSort}
                />
                <SortableTableHead
                  label="Status"
                  sortKey="status"
                  activeKey={sort.key}
                  direction={sort.direction}
                  onSort={changeSort}
                  className="w-36"
                />
                <TableHead className="w-28">Manual action</TableHead>
                <SortableTableHead
                  label="Messages"
                  sortKey="messages"
                  activeKey={sort.key}
                  direction={sort.direction}
                  onSort={changeSort}
                  className="w-24 text-right"
                />
              </TableRow>
            </TableHeader>
            <TableBody>
              {visibleGroups.map((x) => {
                const key = keyOf(x);
                const showPage =
                  Boolean(pageUrls[key]) &&
                  (methods[key] === 'manual' ||
                    results[key] === 'endpoint_failed');
                return (
                  <TableRow key={key}>
                    <TableCell>
                      <Checkbox
                        disabled={
                          methods[key] === 'manual' ||
                          methods[key] === 'unavailable'
                        }
                        checked={selected.has(key)}
                        onCheckedChange={(checked) =>
                          setSelected((old) => {
                            const next = new Set(old);
                            if (checked) next.add(key);
                            else next.delete(key);
                            return next;
                          })
                        }
                      />
                    </TableCell>
                    <TableCell className="min-w-0 overflow-hidden">
                      <p className="truncate text-sm font-medium">{x.sender}</p>
                      <p className="truncate text-xs text-muted-foreground">
                        {x.list_id || x.sender_domain}
                      </p>
                    </TableCell>
                    <TableCell className="w-36">
                      <Badge
                        variant={
                          [
                            'unsubscribed',
                            'email_fallback',
                            'resumed',
                          ].includes(results[key])
                            ? 'default'
                            : 'secondary'
                        }
                      >
                        {(
                          results[key] ||
                          methods[key] ||
                          'analyzing'
                        ).replaceAll('_', ' ')}
                      </Badge>
                    </TableCell>
                    <TableCell className="w-28">
                      {showPage && (
                        <a
                          href={pageUrls[key]}
                          target="_blank"
                          rel="noopener noreferrer"
                          className={buttonVariants({
                            variant: 'outline',
                            size: 'xs',
                          })}
                        >
                          <ExternalLink />
                          Open page
                        </a>
                      )}
                    </TableCell>
                    <TableCell className="w-24 text-right font-semibold">
                      {x.message_count.toLocaleString()}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      </div>
    </main>
  );
}
