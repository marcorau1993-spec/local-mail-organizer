'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import {
  Archive,
  ArrowLeft,
  Bot,
  Building2,
  CheckCircle2,
  Clock3,
  Eye,
  FileSearch,
  Loader2,
  Mail,
  Search,
  ShieldCheck,
  Trash2,
} from 'lucide-react';
import {
  AccountSwitcher,
  useAccountSelection,
} from '@/components/account-switcher';
import {
  filterAndSort,
  nextSort,
  SortableTableHead,
  TableFilterBar,
  type SortDirection,
} from '@/components/table-tools';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

const API_URL = 'http://127.0.0.1:8765';
export type IntelligenceView =
  | 'actions'
  | 'search'
  | 'documents'
  | 'relationships'
  | 'quality'
  | 'health';
type Mail = {
  job_id: string;
  folder: string;
  uid: string;
  subject: string;
  sender: string;
  sender_domain: string;
  size_bytes: number;
  internal_date?: string;
  search_score?: number;
  matched_terms?: string[];
  matched_fields?: string[];
  body_snippet?: string;
};
type ActionItem = Mail & {
  action_type: string;
  priority: number;
  reason: string;
  status: string;
  age_days: number;
  unread: boolean;
};
type Company = {
  company: string;
  messages: number;
  bytes: number;
  identity_count: number;
  identities: string[];
};
type Attachment = Mail & {
  filename: string;
  content_type: string;
  category: string;
  copies: number;
  sha256: string;
  extracted_text?: string;
  extraction_status?: string;
  extraction_method?: string;
};
type CompanyDetail = {
  company: string;
  messages: number;
  bytes: number;
  identities: Array<{
    sender: string;
    messages: number;
    bytes: number;
    oldest_date?: string;
    newest_date?: string;
  }>;
  message_items: Mail[];
};
type ActionAnalysis = {
  summary: string;
  next_action: string;
  urgency: 'low' | 'medium' | 'high';
  due_date?: string | null;
  confidence: number;
};
type Suggestion = {
  id: string;
  sender: string;
  sender_domain: string;
  subject_pattern: string;
  message_count: number;
  total_bytes: number;
  category: string;
  recommendation: string;
  confidence: number;
};
const formatBytes = (value = 0) =>
  value >= 1_073_741_824
    ? `${(value / 1_073_741_824).toFixed(1)} GB`
    : value >= 1_048_576
      ? `${(value / 1_048_576).toFixed(1)} MB`
      : `${(value / 1024).toFixed(1)} KB`;
const TITLES: Record<IntelligenceView, [string, string]> = {
  actions: [
    'Action Inbox',
    'Deadlines, payments, replies, appointments, deliveries, and security actions detected locally.',
  ],
  search: [
    'Smart Search',
    'Search local message content and metadata, then let Qwen rank only supported matches.',
  ],
  documents: [
    'Documents & lifecycle',
    'Index attachment metadata and review contracts, orders, finance, and travel records.',
  ],
  relationships: [
    'Companies & relationships',
    'Merge sender aliases and subdomains into a clearer company-level view.',
  ],
  quality: [
    'AI Quality Center',
    'Measure Qwen against your account-local corrections instead of guessing about quality.',
  ],
  health: [
    'Mailbox Health',
    'Track mailbox size, clutter ratios, folder coverage, and scan history.',
  ],
};
const companyAccessors: Record<string, (item: Company) => string | number> = {
  company: (item) => item.company,
  count: (item) => item.messages,
  aliases: (item) => item.identity_count,
  size: (item) => item.bytes,
};
const actionAccessors: Record<string, (item: ActionItem) => string | number> = {
  message: (item) => `${item.subject} ${item.sender}`,
  folder: (item) => item.folder,
  priority: (item) => item.priority,
  status: (item) => item.status,
};
const attachmentAccessors: Record<
  string,
  (item: Attachment) => string | number
> = {
  attachment: (item) => `${item.filename} ${item.subject}`,
  category: (item) => item.category,
  copies: (item) => item.copies,
  size: (item) => item.size_bytes,
};

export function IntelligenceWorkspace({ view }: { view: IntelligenceView }) {
  const { accounts, accountId, setAccountId } = useAccountSelection();
  const [data, setData] = useState<Record<string, unknown>>({});
  const [query, setQuery] = useState('');
  const [filter, setFilter] = useState('');
  const [pending, setPending] = useState(false);
  const [indexPending, setIndexPending] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [sort, setSort] = useState<{ key: string; direction: SortDirection }>({
    key: 'count',
    direction: 'desc',
  });
  const [title, description] = TITLES[view];

  const load = useCallback(async () => {
    if (!accountId) return;
    const endpoint =
      view === 'actions'
        ? 'action-inbox'
        : view === 'search'
          ? 'content-index'
        : view === 'documents'
          ? 'attachments'
          : view === 'relationships'
            ? 'relationships'
            : view === 'quality'
              ? 'quality'
              : view === 'health'
                ? 'health'
                : null;
    if (!endpoint) return;
    const response = await fetch(
      `${API_URL}/api/intelligence/${endpoint}?account_id=${encodeURIComponent(accountId)}`,
      { cache: 'no-store' },
    );
    if (!response.ok) throw new Error(`Could not load ${title}`);
    const payload = (await response.json()) as Record<string, unknown>;
    if (view === 'documents') {
      const lifecycle = await fetch(
        `${API_URL}/api/intelligence/lifecycle?account_id=${encodeURIComponent(accountId)}`,
        { cache: 'no-store' },
      );
      if (lifecycle.ok) Object.assign(payload, await lifecycle.json());
    }
    setData((current) => (view === 'search' ? { ...current, ...payload } : payload));
  }, [accountId, title, view]);
  useEffect(() => {
    const timer = window.setTimeout(
      () => void load().catch((reason) => setError(reason.message)),
      0,
    );
    return () => window.clearTimeout(timer);
  }, [load]);
  useEffect(() => {
    const run = data.run as { status?: string } | undefined;
    if (view !== 'search' || run?.status !== 'running') return;
    const timer = window.setInterval(() => void load(), 1500);
    return () => window.clearInterval(timer);
  }, [data.run, load, view]);

  async function search() {
    if (!accountId || query.trim().length < 2) return;
    setPending(true);
    setError('');
    setMessage('');
    try {
      const response = await fetch(`${API_URL}/api/intelligence/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ account_id: accountId, query }),
      });
      const payload = (await response.json()) as Record<string, unknown> & {
        detail?: string;
      };
      if (!response.ok)
        throw new Error(payload.detail || 'Smart Search stopped safely');
      setData((current) => ({ ...current, ...payload }));
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : 'Search stopped safely',
      );
    } finally {
      setPending(false);
    }
  }
  async function startContentIndex() {
    if (!accountId) return;
    setIndexPending(true);
    setError('');
    setMessage('');
    try {
      const response = await fetch(
        `${API_URL}/api/intelligence/content-index/start`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ account_id: accountId }),
        },
      );
      const payload = (await response.json()) as { detail?: string };
      if (!response.ok)
        throw new Error(payload.detail || 'Content indexing could not start');
      setMessage(
        'Private content indexing started. Messages are read with BODY.PEEK and remain unread.',
      );
      await load();
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : 'Content indexing stopped safely',
      );
    } finally {
      setIndexPending(false);
    }
  }
  async function clearContentIndex() {
    if (!accountId) return;
    if (
      !window.confirm(
        'Delete the locally stored message-content index for this mailbox? Source mail is not changed.',
      )
    )
      return;
    setIndexPending(true);
    setError('');
    try {
      const response = await fetch(
        `${API_URL}/api/intelligence/content-index?account_id=${encodeURIComponent(accountId)}`,
        { method: 'DELETE' },
      );
      const payload = (await response.json()) as { detail?: string };
      if (!response.ok)
        throw new Error(payload.detail || 'Content index could not be cleared');
      setData({});
      setMessage(
        'Local message-content index deleted. Source mail was not changed.',
      );
      await load();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : 'Content index cleanup failed',
      );
    } finally {
      setIndexPending(false);
    }
  }
  async function setActionState(item: ActionItem, status: string) {
    const response = await fetch(
      `${API_URL}/api/intelligence/action-inbox/state`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          account_id: accountId,
          job_id: item.job_id,
          folder: item.folder,
          uid: item.uid,
          status,
        }),
      },
    );
    if (!response.ok) {
      setError('Could not update action status');
      return;
    }
    setData((current) => ({
      ...current,
      items: ((current.items as ActionItem[]) ?? []).map((candidate) =>
        candidate.job_id === item.job_id &&
        candidate.folder === item.folder &&
        candidate.uid === item.uid
          ? { ...candidate, status }
          : candidate,
      ),
    }));
  }
  async function scanAttachments() {
    if (!accountId) return;
    setPending(true);
    setError('');
    setMessage(
      'Reading the 100 largest indexed messages without marking them as read…',
    );
    try {
      const response = await fetch(
        `${API_URL}/api/intelligence/attachments/scan`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ account_id: accountId, limit: 100 }),
        },
      );
      const payload = (await response.json()) as Record<string, unknown> & {
        detail?: string;
        indexed_messages?: number;
        indexed_attachments?: number;
      };
      if (!response.ok)
        throw new Error(payload.detail || 'Attachment scan stopped safely');
      setData((current) => ({ ...current, ...payload }));
      setMessage(
        `${payload.indexed_attachments ?? 0} attachments indexed from ${payload.indexed_messages ?? 0} messages.`,
      );
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : 'Attachment scan stopped safely',
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
          <ArrowLeft size={16} /> Overview
        </Link>
        <div className="mt-7 flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="eyebrow">Local Qwen intelligence</p>
            <h1 className="mt-2 text-3xl font-semibold">{title}</h1>
            <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
              {description}
            </p>
            <AccountSwitcher
              accounts={accounts}
              accountId={accountId}
              onChange={setAccountId}
              className="mt-4"
            />
          </div>
          <Badge variant="secondary">
            <ShieldCheck /> Local only
          </Badge>
        </div>
        {error && (
          <Alert variant="destructive" className="mt-5">
            <AlertTitle>Stopped safely</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {message && (
          <Alert className="mt-5">
            <AlertTitle>{pending ? 'Working locally' : 'Completed'}</AlertTitle>
            <AlertDescription>{message}</AlertDescription>
          </Alert>
        )}
        {view === 'actions' && (
          <ActionsView
            accountId={accountId}
            data={data}
            filter={filter}
            setFilter={setFilter}
            setState={setActionState}
            reload={load}
          />
        )}
        {view === 'search' && (
          <SearchView
            data={data}
            query={query}
            setQuery={setQuery}
            pending={pending}
            indexPending={indexPending}
            search={search}
            startIndex={startContentIndex}
            clearIndex={clearContentIndex}
          />
        )}
        {view === 'documents' && (
          <DocumentsView
            accountId={accountId}
            data={data}
            pending={pending}
            scan={scanAttachments}
            reload={load}
            filter={filter}
            setFilter={setFilter}
          />
        )}
        {view === 'relationships' && (
          <RelationshipsView
            accountId={accountId}
            data={data}
            filter={filter}
            setFilter={setFilter}
            sort={sort}
            setSort={setSort}
            reload={load}
          />
        )}
        {view === 'quality' && <QualityView data={data} />}
        {view === 'health' && <HealthView data={data} />}
      </div>
    </main>
  );
}

function ActionsView({
  accountId,
  data,
  filter,
  setFilter,
  setState,
  reload,
}: {
  accountId: string;
  data: Record<string, unknown>;
  filter: string;
  setFilter: (value: string) => void;
  setState: (item: ActionItem, status: string) => Promise<void>;
  reload: () => Promise<void>;
}) {
  const [sort, setSort] = useState<{
    key: string;
    direction: SortDirection;
  }>({ key: 'priority', direction: 'desc' });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [pendingKey, setPendingKey] = useState('');
  const [notice, setNotice] = useState('');
  const [localError, setLocalError] = useState('');
  const [analyses, setAnalyses] = useState<Record<string, ActionAnalysis>>({});
  const keyOf = (item: ActionItem) =>
    `${item.job_id}:${item.folder}:${item.uid}`;
  const allItems = (data.items as ActionItem[]) ?? [];
  const items = filterAndSort(
    allItems,
    filter,
    (item) =>
      `${item.subject} ${item.sender} ${item.action_type} ${item.status} ${item.folder}`,
    actionAccessors[sort.key],
    sort.direction,
  );
  const summary = (data.summary as Record<string, number>) ?? {};
  const selectedItems = allItems.filter((item) => selected.has(keyOf(item)));

  async function runMailboxAction(action: 'archive' | 'delete') {
    if (!selectedItems.length) return;
    setPendingKey(action);
    setLocalError('');
    setNotice('');
    const body = {
      action,
      confirmed: true,
      items: selectedItems.map(({ job_id, folder, uid }) => ({
        job_id,
        folder,
        uid,
      })),
    };
    try {
      const previewResponse = await fetch(
        `${API_URL}/api/mail/actions/preview`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        },
      );
      const preview = (await previewResponse.json()) as {
        count?: number;
        bytes?: number;
        detail?: unknown;
      };
      if (!previewResponse.ok)
        throw new Error(
          typeof preview.detail === 'string'
            ? preview.detail
            : 'Safety Rules blocked one or more selected messages',
        );
      const label = action === 'archive' ? 'Archive' : 'Move to Trash';
      if (
        !window.confirm(
          `${label} ${preview.count ?? selectedItems.length} selected action message(s), ${formatBytes(preview.bytes ?? 0)} total?`,
        )
      )
        return;
      const response = await fetch(`${API_URL}/api/mail/actions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const result = (await response.json()) as {
        completed?: number;
        failed?: number;
        unavailable?: number;
        detail?: string;
      };
      if (!response.ok)
        throw new Error(result.detail || 'Mailbox action stopped safely');
      if (!(result.completed ?? 0))
        throw new Error(
          `${result.unavailable ?? 0} messages were no longer at the scanned location and ${result.failed ?? 0} failed. Run a new complete scan.`,
        );
      setNotice(
        `${result.completed} message(s) ${action === 'archive' ? 'archived' : 'moved to Trash'}.`,
      );
      setSelected(new Set());
      await reload();
    } catch (reason) {
      setLocalError(
        reason instanceof Error ? reason.message : 'Mailbox action stopped safely',
      );
    } finally {
      setPendingKey('');
    }
  }

  async function analyze(item: ActionItem) {
    const key = keyOf(item);
    setPendingKey(key);
    setLocalError('');
    try {
      const response = await fetch(
        `${API_URL}/api/intelligence/action-inbox/review`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            account_id: accountId,
            job_id: item.job_id,
            folder: item.folder,
            uid: item.uid,
          }),
        },
      );
      const result = (await response.json()) as ActionAnalysis & {
        detail?: string;
      };
      if (!response.ok)
        throw new Error(result.detail || 'Local Qwen review stopped safely');
      setAnalyses((current) => ({ ...current, [key]: result }));
    } catch (reason) {
      setLocalError(
        reason instanceof Error ? reason.message : 'Local Qwen review stopped safely',
      );
    } finally {
      setPendingKey('');
    }
  }

  return (
    <>
      <div className="mt-6 grid gap-3 sm:grid-cols-4">
        {['open', 'waiting', 'done', 'dismissed'].map((status) => (
          <div className="metric-card" key={status}>
            <p className="metric-label">{status}</p>
            <p className="metric-value">{summary[status] ?? 0}</p>
          </div>
        ))}
      </div>
      <section className="panel mt-4 overflow-x-auto">
        <div className="mb-4 flex flex-wrap items-center gap-2 rounded-xl border bg-muted/20 p-3">
          <Button
            variant="outline"
            disabled={!selected.size || Boolean(pendingKey)}
            onClick={() => void runMailboxAction('archive')}
          >
            <Archive /> Archive selected
          </Button>
          <Button
            variant="destructive"
            disabled={!selected.size || Boolean(pendingKey)}
            onClick={() => void runMailboxAction('delete')}
          >
            <Trash2 /> Move selected to Trash
          </Button>
          <Button
            variant="secondary"
            disabled={!items.length || Boolean(pendingKey)}
            onClick={() =>
              setSelected(new Set(items.slice(0, 25).map((item) => keyOf(item))))
            }
          >
            Select visible (max 25)
          </Button>
          <Button
            variant="ghost"
            disabled={!selected.size}
            onClick={() => setSelected(new Set())}
          >
            Clear
          </Button>
          <span className="ml-auto text-sm font-semibold">
            {selected.size} selected
          </span>
        </div>
        <p className="mb-4 text-xs text-muted-foreground">
          Only explicit requests from the last 45 days are shown. Historical mail,
          newsletters, filed records, and duplicate threads are excluded.
        </p>
        {localError && (
          <Alert variant="destructive" className="mb-4">
            <AlertTitle>No mailbox change was made</AlertTitle>
            <AlertDescription>{localError}</AlertDescription>
          </Alert>
        )}
        {notice && (
          <Alert className="mb-4">
            <AlertTitle>Action completed</AlertTitle>
            <AlertDescription>{notice}</AlertDescription>
          </Alert>
        )}
        <TableFilterBar
          value={filter}
          onChange={setFilter}
          shown={items.length}
          total={allItems.length}
          placeholder="Filter action, sender, subject, or status…"
        />
        <Table className="table-fixed">
          <colgroup>
            <col className="w-12" />
            <col />
            <col className="w-28" />
            <col className="w-80" />
          </colgroup>
          <TableHeader>
            <TableRow>
              <TableHead aria-label="Select message" />
              {[
                ['message', 'Action / message'],
                ['priority', 'Priority'],
                ['status', 'Workflow'],
              ].map(([key, label]) => (
                <SortableTableHead
                  key={key}
                  label={label}
                  sortKey={key}
                  activeKey={sort.key}
                  direction={sort.direction}
                  onSort={(nextKey) =>
                    setSort((old) =>
                      nextSort(old.key, old.direction, nextKey),
                    )
                  }
                />
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((item) => (
              <TableRow key={`${item.job_id}:${item.folder}:${item.uid}`}>
                <TableCell>
                  <Checkbox
                    checked={selected.has(keyOf(item))}
                    onCheckedChange={(checked) =>
                      setSelected((current) => {
                        const next = new Set(current);
                        if (checked) next.add(keyOf(item));
                        else next.delete(keyOf(item));
                        return next;
                      })
                    }
                    aria-label={`Select ${item.subject}`}
                  />
                </TableCell>
                <TableCell>
                  <p className="font-semibold">{item.subject}</p>
                  <p className="text-xs text-muted-foreground">
                    {item.sender} · {item.folder} · {item.age_days} day(s) old
                  </p>
                  <p className="mt-1 text-xs">{item.reason}</p>
                  {analyses[keyOf(item)] && (
                    <div className="mt-3 rounded-lg border bg-background p-3 text-xs">
                      <p className="font-semibold">
                        Qwen: {analyses[keyOf(item)].summary}
                      </p>
                      <p className="mt-1">
                        Next: {analyses[keyOf(item)].next_action}
                      </p>
                      <p className="mt-1 text-muted-foreground">
                        {analyses[keyOf(item)].urgency} urgency ·{' '}
                        {analyses[keyOf(item)].confidence}% confidence
                        {analyses[keyOf(item)].due_date
                          ? ` · due ${analyses[keyOf(item)].due_date}`
                          : ''}
                      </p>
                    </div>
                  )}
                </TableCell>
                <TableCell>
                  <p className="font-semibold">{item.priority}/100</p>
                  <p className="text-xs text-muted-foreground">
                    {item.unread ? 'Unread' : 'Read'} · {item.action_type}
                  </p>
                </TableCell>
                <TableCell>
                  <div className="flex flex-wrap gap-1">
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={Boolean(pendingKey)}
                      onClick={() => void analyze(item)}
                    >
                      {pendingKey === keyOf(item) ? (
                        <Loader2 className="animate-spin" />
                      ) : (
                        <Eye />
                      )}
                      Review with Qwen
                    </Button>
                    <Button
                      size="sm"
                      variant={item.status === 'done' ? 'default' : 'outline'}
                      onClick={() => void setState(item, 'done')}
                    >
                      <CheckCircle2 />
                      Done
                    </Button>
                    <Button
                      size="sm"
                      variant={
                        item.status === 'waiting' ? 'secondary' : 'ghost'
                      }
                      onClick={() => void setState(item, 'waiting')}
                    >
                      <Clock3 />
                      Waiting
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => void setState(item, 'dismissed')}
                    >
                      Dismiss
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
            {!items.length && (
              <TableRow>
                <TableCell colSpan={4} className="py-12 text-center">
                  <CheckCircle2 className="mx-auto mb-2 text-safe" />
                  <p className="font-semibold">No current action request found</p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Nothing is shown merely because an old email contains words
                    such as password, invoice, or appointment.
                  </p>
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </section>
    </>
  );
}
function SearchView({
  data,
  query,
  setQuery,
  pending,
  indexPending,
  search,
  startIndex,
  clearIndex,
}: {
  data: Record<string, unknown>;
  query: string;
  setQuery: (value: string) => void;
  pending: boolean;
  indexPending: boolean;
  search: () => Promise<void>;
  startIndex: () => Promise<void>;
  clearIndex: () => Promise<void>;
}) {
  const results = (data.results as Mail[]) ?? [];
  const searched = typeof data.query === 'string';
  const indexRun = data.run as
    | {
        status: string;
        total_messages: number;
        processed_messages: number;
        indexed_messages: number;
        skipped_messages: number;
        progress_percent: number;
        current_folder?: string;
        error?: string;
      }
    | undefined;
  const indexedMessages = Number(data.indexed_messages ?? 0);
  const scanMessages = Number(data.scan_messages ?? 0);
  const indexing = indexRun?.status === 'running';
  return (
    <>
      <section className="panel mt-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="flex items-center gap-2 text-lg font-semibold">
              <FileSearch size={19} /> Private content index
            </h2>
            <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
              Builds a local FTS5 index from message text without marking mail
              as read. Attachments are excluded; oversized messages remain
              searchable by subject and sender only. Extracted text stays in
              the ignored local SQLite database until you clear it here.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {indexedMessages > 0 && (
              <Button
                variant="ghost"
                disabled={indexPending || indexing}
                onClick={() => void clearIndex()}
              >
                <Trash2 /> Clear local index
              </Button>
            )}
            <Button
              variant="outline"
              disabled={indexPending || indexing || !data.scan_job_id}
              onClick={() => void startIndex()}
            >
              {indexing ? <Loader2 className="animate-spin" /> : <FileSearch />}
              {indexedMessages ? 'Resume / update index' : 'Build content index'}
            </Button>
          </div>
        </div>
        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          <div className="rounded-lg border p-3">
            <p className="text-xl font-semibold">
              {indexedMessages.toLocaleString()}
            </p>
            <p className="text-xs text-muted-foreground">
              of {scanMessages.toLocaleString()} messages indexed
            </p>
          </div>
          <div className="rounded-lg border p-3">
            <p className="text-xl font-semibold">
              {indexRun?.progress_percent ?? (indexedMessages ? 100 : 0)}%
            </p>
            <p className="text-xs text-muted-foreground">
              {indexing
                ? `Reading ${indexRun?.current_folder ?? 'mailbox'}…`
                : indexRun?.status ?? 'not started'}
            </p>
          </div>
          <div className="rounded-lg border p-3">
            <p className="text-xl font-semibold">
              {(indexRun?.skipped_messages ?? 0).toLocaleString()}
            </p>
            <p className="text-xs text-muted-foreground">
              unavailable or body-size limited
            </p>
          </div>
        </div>
        {indexRun?.error && (
          <p className="mt-3 text-xs text-warning">{indexRun.error}</p>
        )}
      </section>
      <section className="panel mt-6">
        <div className="flex gap-2">
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') void search();
            }}
            placeholder="e.g. invoices for the 3D printer from 2024"
          />
          <Button
            disabled={pending || query.trim().length < 2}
            onClick={() => void search()}
          >
            {pending ? <Loader2 className="animate-spin" /> : <Search />}Search
            with Qwen
          </Button>
        </div>
        <p className="mt-3 text-xs text-muted-foreground">
          {typeof data.explanation === 'string'
            ? data.explanation
            : 'Search subjects, senders, folders, dates, indexed message text, and meaning using local Qwen.'}
        </p>
        {searched && (
          <p className="mt-2 text-xs font-medium">
            {results.length
              ? `${results.length} trustworthy match(es) after strict term matching and local Qwen ranking.`
              : 'No trustworthy match. Nothing is shown when every search term cannot be supported by local metadata or indexed content.'}
          </p>
        )}
      </section>
      <section className="panel mt-4">
        <div className="space-y-2">
          {results.map((item) => (
            <div
              key={`${item.job_id}:${item.folder}:${item.uid}`}
              className="grid gap-2 rounded-xl border p-4 sm:grid-cols-[1fr_180px_100px]"
            >
              <div>
                <p className="font-semibold">{item.subject}</p>
                <p className="text-xs text-muted-foreground">{item.sender}</p>
                {item.matched_fields?.length ? (
                  <p className="mt-1 text-xs text-muted-foreground">
                    Matched {item.matched_terms?.join(', ')} in{' '}
                    {item.matched_fields.join(', ')}
                  </p>
                ) : null}
                {item.body_snippet ? (
                  <p className="mt-2 line-clamp-2 text-xs text-muted-foreground">
                    {item.body_snippet.replaceAll('[', '').replaceAll(']', '')}
                  </p>
                ) : null}
              </div>
              <span className="text-sm">{item.folder}</span>
              <span className="text-right text-sm">
                {formatBytes(item.size_bytes)}
              </span>
            </div>
          ))}
          {!results.length && (
            <p className="py-10 text-center text-sm text-muted-foreground">
              {searched
                ? 'No relevant messages found. Try a sender address, exact brand, subject term, or year.'
                : 'Ask a question to search the latest complete scan.'}
            </p>
          )}
        </div>
      </section>
    </>
  );
}
function DocumentsView({
  accountId,
  data,
  pending,
  scan,
  reload,
  filter,
  setFilter,
}: {
  accountId: string;
  data: Record<string, unknown>;
  pending: boolean;
  scan: () => Promise<void>;
  reload: () => Promise<void>;
  filter: string;
  setFilter: (value: string) => void;
}) {
  const [sort, setSort] = useState<{
    key: string;
    direction: SortDirection;
  }>({ key: 'size', direction: 'desc' });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [extracting, setExtracting] = useState(false);
  const [notice, setNotice] = useState('');
  const [extractError, setExtractError] = useState('');
  const summary = (data.summary as Record<string, number>) ?? {};
  const allItems = (data.items as Attachment[]) ?? [];
  const items = filterAndSort(
    allItems,
    filter,
    (item) =>
      `${item.filename} ${item.category} ${item.subject} ${item.sender} ${item.folder}`,
    attachmentAccessors[sort.key],
    sort.direction,
  );
  const entities = (data.entities as Record<string, Suggestion[]>) ?? {};
  const keyOf = (item: Attachment) => `${item.job_id}:${item.folder}:${item.uid}:${item.sha256}`;
  async function extractSelected() {
    const chosen = allItems.filter((item) => selected.has(keyOf(item))).slice(0, 5);
    if (!chosen.length) return;
    setExtracting(true);
    setExtractError('');
    setNotice('');
    try {
      const response = await fetch(`${API_URL}/api/intelligence/attachments/extract`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          account_id: accountId,
          items: chosen.map(({ job_id, folder, uid, sha256 }) => ({ job_id, folder, uid, sha256 })),
        }),
      });
      const payload = (await response.json()) as { completed?: number; unsupported?: number; failed?: number; detail?: string };
      if (!response.ok) throw new Error(payload.detail || 'Local extraction stopped safely');
      setNotice(`${payload.completed ?? 0} extracted · ${payload.unsupported ?? 0} unsupported · ${payload.failed ?? 0} failed`);
      setSelected(new Set());
      await reload();
    } catch (reason) {
      setExtractError(reason instanceof Error ? reason.message : 'Local extraction stopped safely');
    } finally {
      setExtracting(false);
    }
  }
  return (
    <>
      <div className="mt-6 grid gap-3 sm:grid-cols-3">
        <div className="metric-card">
          <p className="metric-label">Attachments</p>
          <p className="metric-value">{summary.attachments ?? 0}</p>
        </div>
        <div className="metric-card">
          <p className="metric-label">Unique files</p>
          <p className="metric-value">{summary.unique_files ?? 0}</p>
        </div>
        <div className="metric-card">
          <p className="metric-label">Indexed size</p>
          <p className="metric-value text-xl">
            {formatBytes(summary.bytes ?? 0)}
          </p>
        </div>
      </div>
      <section className="panel mt-4">
        <div className="flex flex-wrap gap-2">
        <Button disabled={pending} onClick={() => void scan()}>
          {pending ? <Loader2 className="animate-spin" /> : <FileSearch />}Scan
          100 largest messages for attachments
        </Button>
        <Button variant="secondary" disabled={!selected.size || extracting} onClick={() => void extractSelected()}>
          {extracting ? <Loader2 className="animate-spin" /> : <Bot />} Extract text with local AI ({selected.size}/5)
        </Button>
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          Metadata scanning stores hashes only. Selected text, PDF, or image attachments can be transcribed locally; images use Qwen Vision and never leave this computer.
        </p>
        {notice && <Alert className="mt-3"><AlertTitle>Extraction completed</AlertTitle><AlertDescription>{notice}</AlertDescription></Alert>}
        {extractError && <Alert variant="destructive" className="mt-3"><AlertTitle>Extraction stopped safely</AlertTitle><AlertDescription>{extractError}</AlertDescription></Alert>}
      </section>
      <section className="panel mt-4 overflow-x-auto">
        <TableFilterBar
          value={filter}
          onChange={setFilter}
          shown={items.length}
          total={allItems.length}
          placeholder="Filter filename, category, subject, or sender…"
        />
        <Table>
          <TableHeader>
            <TableRow>
              {[
                ['attachment', 'Attachment'],
                ['category', 'Category'],
                ['copies', 'Copies'],
                ['size', 'Size'],
              ].map(([key, label]) => (
                <SortableTableHead
                  key={key}
                  label={label}
                  sortKey={key}
                  activeKey={sort.key}
                  direction={sort.direction}
                  onSort={(nextKey) =>
                    setSort((old) =>
                      nextSort(old.key, old.direction, nextKey),
                    )
                  }
                />
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((item) => (
              <TableRow
                key={`${item.job_id}:${item.folder}:${item.uid}:${item.filename}:${item.sha256}`}
              >
                <TableCell>
                  <div className="flex items-start gap-3">
                  <Checkbox checked={selected.has(keyOf(item))} disabled={!selected.has(keyOf(item)) && selected.size >= 5} onCheckedChange={(checked) => setSelected((current) => { const next = new Set(current); if (checked) next.add(keyOf(item)); else next.delete(keyOf(item)); return next; })} />
                  <div><p className="font-semibold">{item.filename}</p>
                  <p className="max-w-2xl truncate text-xs text-muted-foreground">
                    {item.subject} · {item.sender}
                  </p>
                  {item.extraction_status && <p className="mt-1 text-xs text-primary">{item.extraction_status.replaceAll('_', ' ')}{item.extraction_method ? ` · ${item.extraction_method.replaceAll('_', ' ')}` : ''}</p>}
                  {item.extracted_text && <p className="mt-1 max-w-2xl line-clamp-2 text-xs text-muted-foreground">{item.extracted_text}</p>}
                  </div></div>
                </TableCell>
                <TableCell>{item.category}</TableCell>
                <TableCell>{item.copies}</TableCell>
                <TableCell className="text-right">
                  {formatBytes(item.size_bytes)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </section>
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        {Object.entries(entities).map(([entity, rows]) => (
          <section className="panel" key={entity}>
            <h2 className="font-semibold capitalize">{entity} records</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              {rows
                .reduce((total, row) => total + row.message_count, 0)
                .toLocaleString()}{' '}
              messages from the latest AI analysis
            </p>
            <div className="mt-3 max-h-72 space-y-2 overflow-auto">
              {rows.slice(0, 30).map((row) => (
                <div className="rounded-lg border p-3 text-sm" key={row.id}>
                  <p className="font-medium">{row.subject_pattern}</p>
                  <p className="text-xs text-muted-foreground">
                    {row.sender} · {row.message_count} mails
                  </p>
                </div>
              ))}
            </div>
          </section>
        ))}
      </div>
    </>
  );
}
function RelationshipsView({
  accountId,
  data,
  filter,
  setFilter,
  sort,
  setSort,
  reload,
}: {
  accountId: string;
  data: Record<string, unknown>;
  filter: string;
  setFilter: (value: string) => void;
  sort: { key: string; direction: SortDirection };
  setSort: React.Dispatch<
    React.SetStateAction<{ key: string; direction: SortDirection }>
  >;
  reload: () => Promise<void>;
}) {
  const [detail, setDetail] = useState<CompanyDetail | null>(null);
  const [detailQuery, setDetailQuery] = useState('');
  const [detailPending, setDetailPending] = useState(false);
  const [detailError, setDetailError] = useState('');
  const [detailNotice, setDetailNotice] = useState('');
  const companies = (data.companies as Company[]) ?? [];
  const visible = filterAndSort(
    companies,
    filter,
    (item) => `${item.company} ${item.identities.join(' ')}`,
    companyAccessors[sort.key],
    sort.direction,
  );

  async function openCompany(company: string) {
    setDetailPending(true);
    setDetailError('');
    setDetailNotice('');
    setDetailQuery('');
    try {
      const response = await fetch(
        `${API_URL}/api/intelligence/company?account_id=${encodeURIComponent(accountId)}&company=${encodeURIComponent(company)}`,
        { cache: 'no-store' },
      );
      const result = (await response.json()) as CompanyDetail & {
        detail?: string;
      };
      if (!response.ok)
        throw new Error(result.detail || 'Could not load sender details');
      setDetail(result);
    } catch (reason) {
      setDetailError(
        reason instanceof Error ? reason.message : 'Could not load sender details',
      );
    } finally {
      setDetailPending(false);
    }
  }

  async function cleanupIdentity(sender: string) {
    setDetailPending(true);
    setDetailError('');
    setDetailNotice('');
    try {
      const base = { account_id: accountId, senders: [sender] };
      const previewResponse = await fetch(
        `${API_URL}/api/mail/senders/cleanup-preview`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...base, confirmed: false }),
        },
      );
      const preview = (await previewResponse.json()) as {
        actionable?: number;
        protected?: number;
        bytes?: number;
        detail?: string;
      };
      if (!previewResponse.ok)
        throw new Error(preview.detail || 'Sender preview stopped safely');
      if (!(preview.actionable ?? 0))
        throw new Error(
          `No actionable messages remain. ${preview.protected ?? 0} are protected.`,
        );
      if (
        !window.confirm(
          `Move ${preview.actionable} message(s) from this exact sender to Trash? ${preview.protected ?? 0} protected message(s) will remain.`,
        )
      )
        return;
      const response = await fetch(`${API_URL}/api/mail/senders/cleanup`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...base, confirmed: true }),
      });
      const result = (await response.json()) as {
        completed?: number;
        protected?: number;
        failed?: number;
        unavailable?: number;
        detail?: string;
      };
      if (!response.ok)
        throw new Error(result.detail || 'Sender cleanup stopped safely');
      if (!(result.completed ?? 0))
        throw new Error(
          `No messages were moved. ${result.unavailable ?? 0} were unavailable and ${result.failed ?? 0} failed.`,
        );
      await reload();
      if (detail) await openCompany(detail.company);
      setDetailNotice(
        `${result.completed} moved to Trash · ${result.protected ?? 0} protected`,
      );
    } catch (reason) {
      setDetailError(
        reason instanceof Error ? reason.message : 'Sender cleanup stopped safely',
      );
    } finally {
      setDetailPending(false);
    }
  }

  const normalizedDetailQuery = detailQuery.toLowerCase();
  const visibleIdentities = (detail?.identities ?? []).filter((item) =>
    item.sender.toLowerCase().includes(normalizedDetailQuery),
  );
  const visibleMessages = (detail?.message_items ?? []).filter((item) =>
    `${item.subject} ${item.sender} ${item.folder}`
      .toLowerCase()
      .includes(normalizedDetailQuery),
  );
  return (
    <>
      <section className="panel mt-6 overflow-x-auto">
      <TableFilterBar
        value={filter}
        onChange={setFilter}
        shown={visible.length}
        total={companies.length}
        placeholder="Filter company, domain, or sender identity…"
      />
      <Table>
        <TableHeader>
          <TableRow>
            <SortableTableHead
              label="Company"
              sortKey="company"
              activeKey={sort.key}
              direction={sort.direction}
              onSort={(key) =>
                setSort((old) => nextSort(old.key, old.direction, key))
              }
            />
            <SortableTableHead
              label="Sender identities"
              sortKey="aliases"
              activeKey={sort.key}
              direction={sort.direction}
              onSort={(key) =>
                setSort((old) => nextSort(old.key, old.direction, key))
              }
            />
            <SortableTableHead
              label="Messages"
              sortKey="count"
              activeKey={sort.key}
              direction={sort.direction}
              onSort={(key) =>
                setSort((old) => nextSort(old.key, old.direction, key))
              }
            />
            <SortableTableHead
              label="Storage"
              sortKey="size"
              activeKey={sort.key}
              direction={sort.direction}
              onSort={(key) =>
                setSort((old) => nextSort(old.key, old.direction, key))
              }
            />
          </TableRow>
        </TableHeader>
        <TableBody>
          {visible.map((item) => (
            <TableRow key={item.company}>
              <TableCell>
                <Button
                  variant="link"
                  className="h-auto p-0 text-left font-semibold"
                  disabled={detailPending}
                  onClick={() => void openCompany(item.company)}
                >
                  <Building2 /> {item.company}
                </Button>
                <p
                  className="max-w-xl truncate text-xs text-muted-foreground"
                  title={item.identities.join('\n')}
                >
                  {item.identities.slice(0, 3).join(' · ')}
                </p>
              </TableCell>
              <TableCell>{item.identity_count}</TableCell>
              <TableCell>{item.messages.toLocaleString()}</TableCell>
              <TableCell>{formatBytes(item.bytes)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      </section>
      <Dialog
        open={Boolean(detail) || Boolean(detailError)}
        onOpenChange={(open) => {
          if (!open) {
            setDetail(null);
            setDetailError('');
            setDetailNotice('');
          }
        }}
      >
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-6xl">
          <DialogHeader>
            <DialogTitle>{detail?.company ?? 'Sender details'}</DialogTitle>
            <DialogDescription>
              Exact identities and messages from the selected mailbox only.
              Public email providers are kept separate by address.
            </DialogDescription>
          </DialogHeader>
          {detailError && (
            <Alert variant="destructive">
              <AlertTitle>Stopped safely</AlertTitle>
              <AlertDescription>{detailError}</AlertDescription>
            </Alert>
          )}
          {detailNotice && (
            <Alert>
              <AlertTitle>Completed</AlertTitle>
              <AlertDescription>{detailNotice}</AlertDescription>
            </Alert>
          )}
          {detail && (
            <>
              <div className="grid gap-3 sm:grid-cols-3">
                <div className="metric-card">
                  <p className="metric-label">Messages</p>
                  <p className="metric-value">{detail.messages.toLocaleString()}</p>
                </div>
                <div className="metric-card">
                  <p className="metric-label">Exact identities</p>
                  <p className="metric-value">{detail.identities.length}</p>
                </div>
                <div className="metric-card">
                  <p className="metric-label">Storage</p>
                  <p className="metric-value text-xl">{formatBytes(detail.bytes)}</p>
                </div>
              </div>
              <Input
                value={detailQuery}
                onChange={(event) => setDetailQuery(event.target.value)}
                placeholder="Search exact email, sender name, subject, or folder…"
              />
              <section>
                <h3 className="mb-2 font-semibold">Sender identities</h3>
                <div className="max-h-72 overflow-auto rounded-xl border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Exact sender</TableHead>
                        <TableHead>Messages</TableHead>
                        <TableHead>Storage</TableHead>
                        <TableHead>Action</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {visibleIdentities.map((identity) => (
                        <TableRow key={identity.sender}>
                          <TableCell className="font-medium">
                            {identity.sender}
                          </TableCell>
                          <TableCell>{identity.messages.toLocaleString()}</TableCell>
                          <TableCell>{formatBytes(identity.bytes)}</TableCell>
                          <TableCell>
                            <Button
                              size="sm"
                              variant="destructive"
                              disabled={detailPending}
                              onClick={() => void cleanupIdentity(identity.sender)}
                            >
                              <Trash2 /> All to Trash
                            </Button>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </section>
              <section>
                <h3 className="mb-2 font-semibold">
                  Messages ({visibleMessages.length} shown)
                </h3>
                <div className="max-h-80 overflow-auto rounded-xl border">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Message</TableHead>
                        <TableHead>Folder</TableHead>
                        <TableHead>Size</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {visibleMessages.map((message) => (
                        <TableRow
                          key={`${message.job_id}:${message.folder}:${message.uid}`}
                        >
                          <TableCell>
                            <p className="font-medium">{message.subject}</p>
                            <p className="text-xs text-muted-foreground">
                              <Mail className="mr-1 inline size-3" />
                              {message.sender}
                            </p>
                          </TableCell>
                          <TableCell>{message.folder}</TableCell>
                          <TableCell>{formatBytes(message.size_bytes)}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </section>
            </>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
function QualityView({ data }: { data: Record<string, unknown> }) {
  const rate =
    typeof data.agreement_rate === 'number'
      ? Math.round(data.agreement_rate * 100)
      : null;
  return (
    <>
      <div className="mt-6 grid gap-4 sm:grid-cols-4">
        <div className="metric-card">
          <Bot className="metric-icon" />
          <p className="metric-label">Local corrections</p>
          <p className="metric-value">{Number(data.feedback_count ?? 0)}</p>
        </div>
        <div className="metric-card">
          <p className="metric-label">Evaluated patterns</p>
          <p className="metric-value">{Number(data.evaluated ?? 0)}</p>
        </div>
        <div className="metric-card">
          <p className="metric-label">Agreements</p>
          <p className="metric-value">{Number(data.agreements ?? 0)}</p>
        </div>
        <div className="metric-card">
          <p className="metric-label">Measured agreement</p>
          <p className="metric-value">{rate === null ? '—' : `${rate}%`}</p>
        </div>
      </div>
      <section className="panel mt-4">
        <h2 className="font-semibold">Quality gate</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          Every Keep, Archive, or Trash correction becomes an account-local
          evaluation case. New Qwen runs are compared with these decisions.
          Deterministic protection rules continue to outrank both Qwen and
          learned cleanup preferences.
        </p>
      </section>
    </>
  );
}

function HealthView({ data }: { data: Record<string, unknown> }) {
  const [filter, setFilter] = useState('');
  const [sort, setSort] = useState<{
    key: string;
    direction: SortDirection;
  }>({ key: 'created', direction: 'desc' });
  const current = (data.current as Record<string, number> | null) ?? null;
  const allHistory =
    (data.history as Array<Record<string, number | string>>) ?? [];
  const healthAccessors: Record<
    string,
    (item: Record<string, number | string>) => string | number
  > = {
    created: (item) => String(item.created_at),
    messages: (item) => Number(item.messages),
    size: (item) => Number(item.bytes),
    newsletters: (item) => Number(item.newsletter_messages),
    large: (item) => Number(item.large_messages),
  };
  const history = filterAndSort(
    allHistory,
    filter,
    (item) =>
      `${item.created_at} ${item.messages} ${item.bytes} ${item.newsletter_messages} ${item.large_messages}`,
    healthAccessors[sort.key],
    sort.direction,
  );
  return (
    <>
      <div className="mt-6 grid gap-4 sm:grid-cols-4">
        <div className="metric-card">
          <p className="metric-label">Health score</p>
          <p className="metric-value">{Number(data.score ?? 0)}/100</p>
        </div>
        <div className="metric-card">
          <p className="metric-label">Indexed messages</p>
          <p className="metric-value">
            {Number(current?.processed_messages ?? 0).toLocaleString()}
          </p>
        </div>
        <div className="metric-card">
          <p className="metric-label">Mailbox size</p>
          <p className="metric-value text-xl">
            {formatBytes(Number(current?.total_bytes ?? 0))}
          </p>
        </div>
        <div className="metric-card">
          <p className="metric-label">Folders covered</p>
          <p className="metric-value">{Number(current?.folders ?? 0)}</p>
        </div>
      </div>
      <section className="panel mt-4 overflow-x-auto">
        <h2 className="mb-4 font-semibold">Complete-scan history</h2>
        <TableFilterBar
          value={filter}
          onChange={setFilter}
          shown={history.length}
          total={allHistory.length}
          placeholder="Filter scan date or metric…"
        />
        <Table>
          <TableHeader>
            <TableRow>
              {[
                ['created', 'Scan'],
                ['messages', 'Messages'],
                ['size', 'Size'],
                ['newsletters', 'Newsletters'],
                ['large', 'Large mails'],
              ].map(([key, label]) => (
                <SortableTableHead
                  key={key}
                  label={label}
                  sortKey={key}
                  activeKey={sort.key}
                  direction={sort.direction}
                  onSort={(nextKey) =>
                    setSort((old) =>
                      nextSort(old.key, old.direction, nextKey),
                    )
                  }
                />
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {history.map((item) => (
              <TableRow key={String(item.id)}>
                <TableCell>
                  {new Date(String(item.created_at)).toLocaleString()}
                </TableCell>
                <TableCell>{Number(item.messages).toLocaleString()}</TableCell>
                <TableCell>{formatBytes(Number(item.bytes))}</TableCell>
                <TableCell>
                  {Number(item.newsletter_messages).toLocaleString()}
                </TableCell>
                <TableCell>
                  {Number(item.large_messages).toLocaleString()}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </section>
    </>
  );
}
