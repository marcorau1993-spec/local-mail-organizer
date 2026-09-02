'use client';

import { useState } from 'react';
import type { SyntheticEvent } from 'react';
import Link from 'next/link';
import {
  ArrowLeft,
  Archive,
  Bot,
  CheckCircle2,
  HardDrive,
  Loader2,
  ScanSearch,
  ShieldAlert,
  ShieldCheck,
} from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Table,
  TableBody,
  TableCell,
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

const API_URL = 'http://127.0.0.1:8765';
type Classification = {
  category: string;
  confidence: number;
  recommendation: string;
  reason: string;
  protected: boolean;
  protection_reason?: string;
};
type ReviewItem = {
  uid: string;
  subject: string;
  sender: string;
  size_bytes: number;
  list_unsubscribe: boolean;
  classification: Classification;
};
type ReviewResult = {
  dry_run: boolean;
  destructive_actions_allowed: boolean;
  count: number;
  items: ReviewItem[];
};

function formatBytes(value: number) {
  return new Intl.NumberFormat('en', {
    style: 'unit',
    unit: 'megabyte',
    maximumFractionDigits: 1,
  }).format(value / 1_048_576);
}
function recommendationLabel(value: string) {
  return value
    .split('_')
    .map((word) => word[0]?.toUpperCase() + word.slice(1))
    .join(' ');
}

export default function ReviewPage() {
  const [username, setUsername] = useState('');
  const [limit, setLimit] = useState(5);
  const [pending, setPending] = useState(false);
  const [result, setResult] = useState<ReviewResult | null>(null);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState<{ key: string; direction: SortDirection }>({
    key: 'confidence',
    direction: 'desc',
  });
  const reviewItems = filterAndSort(
    result?.items ?? [],
    query,
    (item) =>
      `${item.subject} ${item.sender} ${item.classification.category} ${item.classification.recommendation} ${item.classification.reason}`,
    (item) =>
      sort.key === 'message'
        ? item.subject
        : sort.key === 'category'
          ? item.classification.category
          : sort.key === 'recommendation'
            ? item.classification.recommendation
            : sort.key === 'safety'
              ? Number(item.classification.protected)
              : sort.key === 'size'
                ? item.size_bytes
                : item.classification.confidence,
    sort.direction,
  );
  const changeSort = (key: string) =>
    setSort((old) => nextSort(old.key, old.direction, key));

  async function runScan(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError('');
    setResult(null);
    try {
      const response = await fetch(`${API_URL}/api/scan/review`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider: 'webde',
          username,
          folder: 'INBOX',
          limit,
        }),
      });
      const payload = (await response.json()) as Partial<ReviewResult> & {
        detail?: string;
      };
      if (!response.ok) throw new Error(payload.detail || 'Review scan failed');
      setResult({
        dry_run: payload.dry_run === true,
        destructive_actions_allowed:
          payload.destructive_actions_allowed === true,
        count: payload.count ?? 0,
        items: payload.items ?? [],
      });
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : 'The local API is unavailable',
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
          className="inline-flex items-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft size={16} /> Back to overview
        </Link>
        <div className="mt-7 flex flex-col justify-between gap-4 md:flex-row md:items-end">
          <div>
            <p className="eyebrow">AI-assisted inbox review</p>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight">
              Review before anything happens.
            </h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
              Qwen classifies a small, bounded set of recent headers. Safety
              rules run after the model and can override every recommendation.
            </p>
          </div>
          <Badge
            variant="outline"
            className="h-7 border-safe/30 bg-safe-soft px-3 text-safe"
          >
            <ShieldCheck /> Dry-run only
          </Badge>
        </div>
        <div className="mt-6 grid gap-5 lg:grid-cols-[340px_minmax(0,1fr)]">
          <aside className="space-y-5">
            <form className="panel space-y-4" onSubmit={runScan}>
              <div className="flex items-center gap-2 font-semibold">
                <ScanSearch className="text-brand" size={18} /> New review scan
              </div>
              <label
                htmlFor="review-account"
                className="block text-sm font-semibold"
              >
                WEB.DE account
              </label>
              <Input
                id="review-account"
                inputMode="email"
                autoComplete="username"
                placeholder="account@web.de"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                required
                className="h-10"
              />
              <label
                htmlFor="review-limit"
                className="block text-sm font-semibold"
              >
                Recent messages
              </label>
              <select
                id="review-limit"
                value={limit}
                onChange={(event) => setLimit(Number(event.target.value))}
                className="h-10 w-full rounded-lg border bg-background px-3 text-sm"
              >
                <option value={3}>3 messages</option>
                <option value={5}>5 messages</option>
                <option value={10}>10 messages</option>
              </select>
              <Button
                type="submit"
                disabled={pending || !username}
                className="h-10 w-full"
              >
                {pending ? <Loader2 className="animate-spin" /> : <Bot />}
                {pending ? 'Qwen is reviewing…' : 'Run safe review'}
              </Button>
              <p className="text-xs leading-5 text-muted-foreground">
                Your address is used only to locate its opaque credential entry.
                It is not saved by this page.
              </p>
            </form>
            <div className="panel">
              <div className="flex items-center gap-2 font-semibold">
                <ShieldAlert className="text-safe" size={18} /> Automatic
                protection
              </div>
              <ul className="mt-4 space-y-3 text-sm text-muted-foreground">
                <li>
                  Financial, legal, security, personal, order, and travel mail
                  is forced to Keep.
                </li>
                <li>Confidence below 90% is forced to Manual Review.</li>
                <li>No Delete recommendation exists in the schema.</li>
              </ul>
            </div>
          </aside>
          <section className="min-w-0">
            {error && (
              <Alert variant="destructive">
                <ShieldAlert />
                <AlertTitle>Review scan stopped safely</AlertTitle>
                <AlertDescription>
                  {error}. Confirm the account credential was saved during setup
                  and Ollama is running.
                </AlertDescription>
              </Alert>
            )}
            {!result && !error && (
              <div className="panel grid min-h-[360px] place-items-center text-center">
                <div>
                  <span className="mx-auto grid size-14 place-items-center rounded-2xl bg-secondary text-brand">
                    <Bot size={25} />
                  </span>
                  <h2 className="mt-4 text-lg font-semibold">
                    Ready for a bounded local scan
                  </h2>
                  <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-muted-foreground">
                    No messages are loaded until you start. The scan fetches
                    selected headers with BODY.PEEK, which does not mark mail as
                    read.
                  </p>
                </div>
              </div>
            )}
            {result && (
              <div className="panel">
                <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="eyebrow">Review queue</p>
                    <h2 className="mt-1 text-lg font-semibold">
                      {result.count} classified messages
                    </h2>
                  </div>
                  <div className="flex gap-2">
                    <Badge variant="secondary">
                      <CheckCircle2 /> Qwen local
                    </Badge>
                    <Badge variant="outline">No actions executed</Badge>
                  </div>
                </div>
                <TableFilterBar
                  value={query}
                  onChange={setQuery}
                  shown={reviewItems.length}
                  total={result.items.length}
                  placeholder="Filter messages, senders, or AI labels…"
                />
                <Table>
                  <TableHeader>
                    <TableRow>
                      <SortableTableHead
                        label="Message"
                        sortKey="message"
                        activeKey={sort.key}
                        direction={sort.direction}
                        onSort={changeSort}
                      />
                      <SortableTableHead
                        label="Category"
                        sortKey="category"
                        activeKey={sort.key}
                        direction={sort.direction}
                        onSort={changeSort}
                      />
                      <SortableTableHead
                        label="Recommendation"
                        sortKey="recommendation"
                        activeKey={sort.key}
                        direction={sort.direction}
                        onSort={changeSort}
                      />
                      <SortableTableHead
                        label="Safety"
                        sortKey="safety"
                        activeKey={sort.key}
                        direction={sort.direction}
                        onSort={changeSort}
                      />
                      <SortableTableHead
                        label="Size"
                        sortKey="size"
                        activeKey={sort.key}
                        direction={sort.direction}
                        onSort={changeSort}
                        className="text-right"
                      />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {reviewItems.map((item) => (
                      <TableRow key={item.uid}>
                        <TableCell className="max-w-[340px] whitespace-normal">
                          <p className="truncate font-semibold">
                            {item.subject}
                          </p>
                          <p className="mt-1 truncate text-xs text-muted-foreground">
                            {item.sender}
                          </p>
                          <p className="mt-1 text-xs text-muted-foreground">
                            {item.classification.reason}
                          </p>
                        </TableCell>
                        <TableCell>
                          <Badge variant="secondary">
                            {item.classification.category}
                          </Badge>
                          <p className="mt-1 text-xs text-muted-foreground">
                            {Math.round(item.classification.confidence * 100)}%
                          </p>
                        </TableCell>
                        <TableCell>
                          <span className="text-sm font-medium">
                            {recommendationLabel(
                              item.classification.recommendation,
                            )}
                          </span>
                          {item.list_unsubscribe && (
                            <p className="mt-1 text-xs text-muted-foreground">
                              Unsubscribe header available
                            </p>
                          )}
                        </TableCell>
                        <TableCell>
                          {item.classification.protected ? (
                            <Badge className="bg-safe text-white">
                              <ShieldCheck /> Protected
                            </Badge>
                          ) : (
                            <Badge variant="outline">Reviewable</Badge>
                          )}
                          <p className="mt-1 max-w-[180px] whitespace-normal text-xs text-muted-foreground">
                            {item.classification.protection_reason}
                          </p>
                        </TableCell>
                        <TableCell className="text-right">
                          <span>{formatBytes(item.size_bytes)}</span>
                          {item.size_bytes >= 10_485_760 && (
                            <p className="mt-1 flex items-center justify-end gap-1 text-xs font-semibold text-brand">
                              <HardDrive size={12} /> Archive candidate
                            </p>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                <div className="mt-5 flex items-center gap-2 rounded-xl border bg-secondary/30 p-4 text-sm text-muted-foreground">
                  <Archive size={17} className="text-brand" />
                  <strong className="text-foreground">
                    Preview only:
                  </strong>{' '}
                  archive, unsubscribe, and Trash actions will be implemented as
                  separately approved transactions.
                </div>
              </div>
            )}
          </section>
        </div>
      </div>
    </main>
  );
}
