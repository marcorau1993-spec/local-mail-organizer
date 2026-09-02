'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import {
  Archive,
  ArrowLeft,
  CheckCircle2,
  ShieldCheck,
  Sparkles,
  Trash2,
} from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Progress } from '@/components/ui/progress';
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
type Run = {
  id: string;
  status: string;
  total_groups: number;
  processed_groups: number;
  error: string | null;
};
type Summary = {
  groups_analyzed: number;
  messages_analyzed: number;
  trash_messages: number;
  trash_bytes: number;
  archive_messages: number;
  archive_bytes: number;
  protected_messages: number;
};
type Suggestion = {
  id: string;
  sender: string;
  sender_domain: string;
  subject_pattern: string;
  message_count: number;
  total_bytes: number;
  oldest_date: string | null;
  newest_date: string | null;
  category: string;
  recommendation: string;
  confidence: number;
  reason: string;
  protected: number;
};
type Filter = 'all' | 'trash_review' | 'archive_review' | 'protected';

function formatBytes(value: number) {
  if (value < 1_048_576) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1_073_741_824) return `${(value / 1_048_576).toFixed(1)} MB`;
  return `${(value / 1_073_741_824).toFixed(1)} GB`;
}

export default function AICleanupPage() {
  const { accounts, accountId, setAccountId } = useAccountSelection();
  const [run, setRun] = useState<Run | null>(null);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState<Filter>('all');
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState<{ key: string; direction: SortDirection }>({
    key: 'messages',
    direction: 'desc',
  });
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');

  const load = useCallback(async () => {
    if (!accountId) {
      setRun(null);
      setSuggestions([]);
      setSummary(null);
      return;
    }
    const response = await fetch(
      `${API_URL}/api/ai-cleanup?account_id=${encodeURIComponent(accountId)}`,
      {
        cache: 'no-store',
      },
    );
    if (!response.ok)
      throw new Error('The local AI cleanup service is unavailable');
    const payload = (await response.json()) as {
      run: Run | null;
      suggestions: Suggestion[];
      summary: Summary | null;
    };
    setRun(payload.run);
    setSuggestions(payload.suggestions);
    setSummary(payload.summary);
  }, [accountId]);

  useEffect(() => {
    const timer = window.setTimeout(
      () =>
        void load().catch((reason) =>
          setError(
            reason instanceof Error
              ? reason.message
              : 'Could not load AI cleanup',
          ),
        ),
      0,
    );
    return () => window.clearTimeout(timer);
  }, [load]);
  useEffect(() => {
    if (run?.status !== 'running') return;
    const timer = window.setInterval(() => void load().catch(() => {}), 2000);
    return () => window.clearInterval(timer);
  }, [run?.status, load]);

  const visible = useMemo(
    () =>
      filterAndSort(
        suggestions.filter(
          (item) =>
            filter === 'all' ||
            (filter === 'protected'
              ? Boolean(item.protected)
              : item.recommendation === filter),
        ),
        query,
        (item) =>
          `${item.sender} ${item.sender_domain} ${item.subject_pattern} ${item.category} ${item.recommendation} ${item.reason}`,
        (item) =>
          sort.key === 'group'
            ? item.sender
            : sort.key === 'recommendation'
              ? item.recommendation
              : sort.key === 'confidence'
                ? item.confidence
                : sort.key === 'messages'
                  ? item.message_count
                  : item.total_bytes,
        sort.direction,
      ),
    [suggestions, filter, query, sort],
  );
  const changeSort = (key: string) =>
    setSort((old) => nextSort(old.key, old.direction, key));
  const selectable = visible.filter((item) => !item.protected);
  const selectedItems = suggestions.filter((item) => selected.has(item.id));
  const selectedMessages = selectedItems.reduce(
    (sum, item) => sum + item.message_count,
    0,
  );
  const selectedBytes = selectedItems.reduce(
    (sum, item) => sum + item.total_bytes,
    0,
  );
  const progress = run?.total_groups
    ? Math.round((run.processed_groups * 100) / run.total_groups)
    : 0;

  async function start() {
    setPending(true);
    setError('');
    setMessage('');
    try {
      const response = await fetch(
        `${API_URL}/api/ai-cleanup/start?account_id=${encodeURIComponent(accountId)}`,
        {
          method: 'POST',
        },
      );
      const payload = (await response.json()) as {
        run_id?: string;
        detail?: string;
      };
      if (!response.ok)
        throw new Error(payload.detail || 'Could not start AI cleanup');
      setSelected(new Set());
      await load();
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : 'Could not start AI cleanup',
      );
    } finally {
      setPending(false);
    }
  }

  async function execute(action: 'archive' | 'trash') {
    if (!run || !selected.size) return;
    const needsTrashApproval =
      action === 'trash' &&
      selectedItems.filter((item) => item.recommendation !== 'trash_review');
    if (
      needsTrashApproval &&
      needsTrashApproval.length > 0 &&
      !window.confirm(
        `${needsTrashApproval.length} selected group(s) are currently marked for Archive. Mark them as Trash review, teach Qwen this preference, and continue? Deterministically protected mail will still be blocked.`,
      )
    )
      return;
    if (
      !window.confirm(
        `${action === 'trash' ? 'Move' : 'Archive'} ${selectedMessages.toLocaleString()} messages from ${selected.size} AI-reviewed groups? Messages with attachments remain protected.`,
      )
    )
      return;
    setPending(true);
    setError('');
    setMessage(
      `${action === 'archive' ? 'Archiving' : 'Moving'} ${selectedMessages.toLocaleString()} messages from ${selected.size} group(s). This can take several minutes for large groups; keep this page open.`,
    );
    try {
      if (needsTrashApproval && needsTrashApproval.length > 0) {
        for (const item of needsTrashApproval) {
          const approval = await fetch(`${API_URL}/api/ai-cleanup/feedback`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              account_id: accountId,
              suggestion_id: item.id,
              decision: 'trash_review',
            }),
          });
          const approvalPayload = (await approval.json()) as {
            detail?: string;
          };
          if (!approval.ok)
            throw new Error(
              approvalPayload.detail || 'Trash approval stopped safely',
            );
        }
      }
      const response = await fetch(`${API_URL}/api/ai-cleanup/actions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          run_id: run.id,
          suggestion_ids: [...selected],
          action,
          confirmed: true,
        }),
      });
      const payload = (await response.json()) as {
        requested?: number;
        moved?: number;
        attachment_protected?: number;
        safety_protected?: number;
        already_completed?: number;
        source_missing?: number;
        failed?: number;
        failure_reasons?: Record<string, number>;
        destination?: string;
        detail?: string;
      };
      if (!response.ok)
        throw new Error(payload.detail || 'Cleanup action stopped safely');
      const failureSummary = payload.failed
        ? `${payload.failed} failed${payload.failure_reasons ? ` (${Object.entries(payload.failure_reasons).map(([reason, count]) => `${reason}: ${count}`).join(', ')})` : ''}`
        : '';
      if (!(payload.moved ?? 0) && !(payload.source_missing ?? 0)) {
        const reasons = [
          payload.attachment_protected
            ? `${payload.attachment_protected} contain attachments`
            : '',
          payload.safety_protected
            ? `${payload.safety_protected} are protected by Safety Rules`
            : '',
          payload.already_completed
            ? `${payload.already_completed} were already processed`
            : '',
          failureSummary,
        ].filter(Boolean);
        throw new Error(
          `No messages were moved${reasons.length ? `: ${reasons.join(' · ')}` : '. Run a new Full mailbox scan and AI analysis.'}`,
        );
      }
      const outcomes = [
        `${payload.moved ?? 0} moved to ${payload.destination}`,
        payload.source_missing
          ? `${payload.source_missing} already absent and reconciled`
          : '',
        payload.attachment_protected
          ? `${payload.attachment_protected} protected attachments`
          : '',
        payload.safety_protected
          ? `${payload.safety_protected} protected by rules`
          : '',
        failureSummary,
      ].filter(Boolean);
      setMessage(
        outcomes.join(' · '),
      );
      setSelected(new Set());
      await load();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : 'Cleanup action stopped safely',
      );
    } finally {
      setPending(false);
    }
  }

  async function teach(
    item: Suggestion,
    decision: 'keep' | 'archive_review' | 'trash_review',
  ) {
    if (!accountId) return;
    setError('');
    const response = await fetch(`${API_URL}/api/ai-cleanup/feedback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        account_id: accountId,
        suggestion_id: item.id,
        decision,
      }),
    });
    const payload = (await response.json()) as { detail?: string };
    if (!response.ok) {
      setError(payload.detail || 'Could not save local feedback');
      return;
    }
    setSuggestions((current) =>
      current.map((candidate) =>
        candidate.id === item.id
          ? {
              ...candidate,
              recommendation: decision,
              protected: Number(decision === 'keep'),
              confidence: 1,
              reason: `Learned from your account-local correction: ${decision.replaceAll('_', ' ')}`,
            }
          : candidate,
      ),
    );
    if (decision === 'keep') {
      setSelected((current) => {
        const next = new Set(current);
        next.delete(item.id);
        return next;
      });
    }
    setMessage(
      'Correction saved locally and will override future Qwen runs for this pattern.',
    );
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
            <p className="eyebrow">Local mailbox intelligence</p>
            <h1 className="mt-2 text-3xl font-semibold">AI Cleanup</h1>
            <AccountSwitcher
              accounts={accounts}
              accountId={accountId}
              onChange={setAccountId}
              className="mt-4"
            />
            <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
              Qwen groups the complete non-newsletter inventory by sender and
              subject pattern, protects sensitive mail, and proposes reviewable
              cleanup.
            </p>
          </div>
          <Button
            onClick={() => void start()}
            disabled={pending || run?.status === 'running'}
          >
            <Sparkles />
            {run ? 'Run new analysis' : 'Analyze mailbox'}
          </Button>
        </div>
        <div className="mt-4">
          <Link
            href="/filing-plan"
            className="text-sm font-semibold text-primary hover:underline"
          >
            Open AI filing plan →
          </Link>
        </div>

        {run && (
          <section className="panel mt-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-sm font-semibold">
                  {run.status === 'running'
                    ? 'Qwen analysis in progress'
                    : 'Latest analysis'}
                </p>
                <p className="text-xs text-muted-foreground">
                  {run.processed_groups.toLocaleString()} of{' '}
                  {run.total_groups.toLocaleString()} groups analyzed
                </p>
              </div>
              <Badge
                variant={
                  run.status.startsWith('completed') ? 'default' : 'secondary'
                }
              >
                {run.status.replaceAll('_', ' ')}
              </Badge>
            </div>
            <Progress value={progress} className="mt-4" />
            <p className="mt-2 text-xs text-muted-foreground">
              {progress}% · Results are saved locally and appear while Qwen
              continues.
            </p>
          </section>
        )}

        <div className="mt-4 grid gap-4 sm:grid-cols-3">
          <article className="metric-card">
            <Trash2 className="metric-icon" />
            <p className="metric-label">Trash review</p>
            <p className="metric-value">
              {(summary?.trash_messages ?? 0).toLocaleString()}
            </p>
            <p className="metric-note">
              {formatBytes(summary?.trash_bytes ?? 0)} · old automated mail
            </p>
          </article>
          <article className="metric-card">
            <Archive className="metric-icon" />
            <p className="metric-label">Archive review</p>
            <p className="metric-value">
              {(summary?.archive_messages ?? 0).toLocaleString()}
            </p>
            <p className="metric-note">
              {formatBytes(summary?.archive_bytes ?? 0)} · retain outside inbox
            </p>
          </article>
          <article className="metric-card">
            <ShieldCheck className="metric-icon" />
            <p className="metric-label">Protected</p>
            <p className="metric-value">
              {(summary?.protected_messages ?? 0).toLocaleString()}
            </p>
            <p className="metric-note">Important, personal, or uncertain</p>
          </article>
        </div>

        <section className="panel mt-4">
          <div className="flex flex-wrap items-center gap-2">
            <Button
              disabled={!selected.size || pending}
              onClick={() => void execute('archive')}
            >
              <Archive />
              {pending ? 'Processing selected…' : 'Archive selected'}
            </Button>
            <Button
              variant="destructive"
              disabled={!selected.size || pending}
              onClick={() => void execute('trash')}
            >
              <Trash2 />
              Move selected to Trash
            </Button>
            <Button
              variant="outline"
              disabled={!selectable.length || pending}
              onClick={() =>
                setSelected(new Set(selectable.slice(0, 25).map((x) => x.id)))
              }
            >
              Select visible (max 25)
            </Button>
            <Button
              variant="ghost"
              disabled={!selected.size || pending}
              onClick={() => setSelected(new Set())}
            >
              Clear
            </Button>
            {(
              ['all', 'trash_review', 'archive_review', 'protected'] as const
            ).map((value) => (
              <Button
                key={value}
                variant={filter === value ? 'secondary' : 'outline'}
                onClick={() => {
                  setFilter(value);
                  setSelected(new Set());
                }}
              >
                {value.replaceAll('_', ' ')}
              </Button>
            ))}
          </div>
          <p className="mt-3 text-xs text-muted-foreground">
            {selected.size} groups · {selectedMessages.toLocaleString()}{' '}
            messages · {formatBytes(selectedBytes)}. Full messages stay local
            and are checked for attachments immediately before any move.
          </p>
        </section>

        {error && (
          <Alert variant="destructive" className="mt-4">
            <AlertTitle>Stopped safely</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {message && (
          <Alert className="mt-4">
            <AlertTitle>
              {pending ? 'Action in progress' : 'Action completed'}
            </AlertTitle>
            <AlertDescription>{message}</AlertDescription>
          </Alert>
        )}

        <section className="panel mt-4 overflow-x-auto">
          <TableFilterBar
            value={query}
            onChange={setQuery}
            shown={visible.length}
            total={suggestions.length}
            placeholder="Filter sender, subject, category, or recommendation…"
          />
          <Table className="table-fixed">
            <TableHeader>
              <TableRow>
                <TableHead className="w-10" />
                <SortableTableHead
                  label="Group"
                  sortKey="group"
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
                  className="w-32"
                />
                <SortableTableHead
                  label="Confidence"
                  sortKey="confidence"
                  activeKey={sort.key}
                  direction={sort.direction}
                  onSort={changeSort}
                  className="w-24"
                />
                <SortableTableHead
                  label="Messages"
                  sortKey="messages"
                  activeKey={sort.key}
                  direction={sort.direction}
                  onSort={changeSort}
                  className="w-24 text-right"
                />
                <SortableTableHead
                  label="Size"
                  sortKey="size"
                  activeKey={sort.key}
                  direction={sort.direction}
                  onSort={changeSort}
                  className="w-24 text-right"
                />
              </TableRow>
            </TableHeader>
            <TableBody>
              {visible.map((item) => (
                <TableRow key={item.id}>
                  <TableCell>
                    <Checkbox
                      disabled={Boolean(item.protected) || pending}
                      checked={selected.has(item.id)}
                      onCheckedChange={(checked) =>
                        setSelected((old) => {
                          const next = new Set(old);
                          if (checked && next.size < 25) next.add(item.id);
                          else if (!checked) next.delete(item.id);
                          return next;
                        })
                      }
                    />
                  </TableCell>
                  <TableCell className="min-w-0 overflow-hidden">
                    <p className="truncate text-sm font-semibold">
                      {item.sender}
                    </p>
                    <p className="truncate text-xs">{item.subject_pattern}</p>
                    <p className="truncate text-xs text-muted-foreground">
                      {item.category} · {item.reason}
                    </p>
                    <div
                      className="mt-2 flex flex-wrap gap-1"
                      aria-label="Teach local AI"
                    >
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => void teach(item, 'keep')}
                      >
                        <CheckCircle2 size={13} /> Keep
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => void teach(item, 'archive_review')}
                      >
                        <Archive size={13} /> Archive
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => void teach(item, 'trash_review')}
                      >
                        <Trash2 size={13} /> Trash
                      </Button>
                    </div>
                  </TableCell>
                  <TableCell className="w-32">
                    <Badge
                      variant={
                        item.protected
                          ? 'secondary'
                          : item.recommendation === 'trash_review'
                            ? 'destructive'
                            : 'default'
                      }
                    >
                      {item.recommendation.replaceAll('_', ' ')}
                    </Badge>
                  </TableCell>
                  <TableCell className="w-24">
                    {Math.round(item.confidence * 100)}%
                  </TableCell>
                  <TableCell className="w-24 text-right font-semibold">
                    {item.message_count.toLocaleString()}
                  </TableCell>
                  <TableCell className="w-24 text-right">
                    {formatBytes(item.total_bytes)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {!visible.length && (
            <p className="py-10 text-center text-sm text-muted-foreground">
              {run?.status === 'running'
                ? 'Qwen is preparing the first groups…'
                : 'Start an analysis to build a cleanup plan.'}
            </p>
          )}
        </section>
      </div>
    </main>
  );
}
