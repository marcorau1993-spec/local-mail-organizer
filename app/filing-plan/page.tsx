'use client';

import { useCallback, useEffect, useState } from 'react';
import Link from 'next/link';
import {
  ArrowLeft,
  FolderInput,
  FolderPlus,
  Power,
  Sparkles,
} from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
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
const FOLDER_CATEGORIES = [
  'Invoices',
  'Orders',
  'Travel',
  'Contracts',
  'Security',
] as const;
type Proposal = {
  id: string;
  bucket: string;
  year: number;
  destination: string;
  reason: string;
  message_count: number;
  total_bytes: number;
};
type Rule = {
  id: string;
  bucket: string;
  target_year: number;
  destination: string;
  enabled: number;
  updated_at: string;
};
function formatBytes(value: number) {
  if (value < 1_048_576) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1_073_741_824) return `${(value / 1_048_576).toFixed(1)} MB`;
  return `${(value / 1_073_741_824).toFixed(1)} GB`;
}

export default function FilingPlanPage() {
  const { accounts, accountId, setAccountId } = useAccountSelection();
  const [runId, setRunId] = useState<string | null>(null);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [rules, setRules] = useState<Rule[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [futureYears, setFutureYears] = useState<0 | 2 | 5 | 10>(2);
  const [prepareYears, setPrepareYears] = useState<2 | 5 | 10>(5);
  const [preparedBuckets, setPreparedBuckets] = useState<Set<string>>(
    new Set(),
  );
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState<{ key: string; direction: SortDirection }>({
    key: 'messages',
    direction: 'desc',
  });
  const visibleProposals = filterAndSort(
    proposals,
    query,
    (item) => `${item.destination} ${item.bucket} ${item.year} ${item.reason}`,
    (item) =>
      sort.key === 'destination'
        ? item.destination
        : sort.key === 'why'
          ? item.reason
          : sort.key === 'messages'
            ? item.message_count
            : item.total_bytes,
    sort.direction,
  );
  const changeSort = (key: string) =>
    setSort((old) => nextSort(old.key, old.direction, key));
  const load = useCallback(async () => {
    if (!accountId) {
      setRunId(null);
      setProposals([]);
      setRules([]);
      return;
    }
    const response = await fetch(
      `${API_URL}/api/filing-plan?account_id=${encodeURIComponent(accountId)}`,
      {
        cache: 'no-store',
      },
    );
    const payload = (await response.json()) as {
      run_id: string | null;
      proposals: Proposal[];
      rules: Rule[];
      detail?: string;
    };
    if (!response.ok)
      throw new Error(payload.detail || 'Could not load filing plan');
    setRunId(payload.run_id);
    setProposals(payload.proposals);
    setRules(payload.rules);
  }, [accountId]);
  useEffect(() => {
    const timer = window.setTimeout(
      () =>
        void load().catch((reason) =>
          setError(
            reason instanceof Error
              ? reason.message
              : 'Could not load filing plan',
          ),
        ),
      0,
    );
    return () => window.clearTimeout(timer);
  }, [load]);
  const chosen = proposals.filter((item) => selected.has(item.id));
  const messages = chosen.reduce((sum, item) => sum + item.message_count, 0);

  async function apply() {
    if (!runId || !selected.size) return;
    if (
      !window.confirm(
        `Create ${selected.size} folder rule(s) and move ${messages.toLocaleString()} existing messages? No messages are deleted.`,
      )
    )
      return;
    setPending(true);
    setError('');
    setMessage('');
    try {
      const response = await fetch(`${API_URL}/api/filing-plan/apply`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          run_id: runId,
          proposal_ids: [...selected],
          confirmed: true,
          future_years: futureYears,
        }),
      });
      const payload = (await response.json()) as {
        moved?: number;
        failed?: number;
        created_rules?: number;
        prepared_future_folders?: number;
        detail?: string;
      };
      if (!response.ok)
        throw new Error(payload.detail || 'Filing stopped safely');
      setMessage(
        `${payload.created_rules ?? 0} rules enabled · ${payload.prepared_future_folders ?? 0} future folders prepared · ${payload.moved ?? 0} messages filed · ${payload.failed ?? 0} failed`,
      );
      setSelected(new Set());
      await load();
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : 'Filing stopped safely',
      );
    } finally {
      setPending(false);
    }
  }
  async function toggle(rule: Rule) {
    setPending(true);
    setError('');
    try {
      const response = await fetch(
        `${API_URL}/api/filing-rules/${rule.id}/state`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enabled: !rule.enabled }),
        },
      );
      if (!response.ok) throw new Error('Could not update filing rule');
      await load();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : 'Could not update filing rule',
      );
    } finally {
      setPending(false);
    }
  }

  async function prepareFolders() {
    if (!preparedBuckets.size) return;
    const folderCount = preparedBuckets.size * (prepareYears + 1);
    if (
      !window.confirm(
        `Create ${folderCount} provider folders and active mailbox rules for ${[...preparedBuckets].join(', ')} from this year through the next ${prepareYears} years?`,
      )
    )
      return;
    setPending(true);
    setError('');
    setMessage('');
    try {
      const response = await fetch(`${API_URL}/api/filing-plan/prepare`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          account_id: accountId,
          buckets: [...preparedBuckets],
          future_years: prepareYears,
          confirmed: true,
        }),
      });
      const payload = (await response.json()) as {
        folders?: string[];
        created_rules?: number;
        provider?: string;
        delimiter?: string;
        detail?: string;
      };
      if (!response.ok)
        throw new Error(payload.detail || 'Folder preparation stopped safely');
      setMessage(
        `${payload.folders?.length ?? 0} folders created on ${payload.provider} using its “${payload.delimiter}” hierarchy · ${payload.created_rules ?? 0} active rules saved`,
      );
      await load();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : 'Folder preparation stopped safely',
      );
    } finally {
      setPending(false);
    }
  }

  async function applySavedRules() {
    if (
      !window.confirm(
        'Apply all active local filing rules to newly analyzed matching messages?',
      )
    )
      return;
    setPending(true);
    setError('');
    setMessage('');
    try {
      const response = await fetch(`${API_URL}/api/filing-rules/apply`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ account_id: accountId, confirmed: true }),
      });
      const payload = (await response.json()) as {
        moved?: number;
        failed?: number;
        matched_rules?: number;
        detail?: string;
      };
      if (!response.ok)
        throw new Error(payload.detail || 'Saved rules stopped safely');
      setMessage(
        `${payload.matched_rules ?? 0} active rules matched · ${payload.moved ?? 0} new messages filed · ${payload.failed ?? 0} failed`,
      );
      await load();
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : 'Saved rules stopped safely',
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
            <p className="eyebrow">AI filing plan</p>
            <h1 className="mt-2 text-3xl font-semibold">
              A place for every important mail.
            </h1>
            <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
              Create year-based folders from Qwen’s protected classifications,
              file existing messages, and retain reusable local organizer rules.
            </p>
            <AccountSwitcher
              accounts={accounts}
              accountId={accountId}
              onChange={setAccountId}
              className="mt-4"
            />
          </div>
          <Badge variant="secondary">
            <Sparkles />
            Local AI suggestions
          </Badge>
        </div>
        <section className="panel mt-6">
          <div className="mb-5 rounded-xl border bg-secondary/30 p-4">
            <p className="font-semibold">Prepare category folders & rules</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Choose categories independently from existing-message proposals.
              Folders are created directly on the selected mail provider, and
              active account-specific rules are saved for the Windows filing
              service.
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {FOLDER_CATEGORIES.map((bucket) => (
                <label
                  key={bucket}
                  className="inline-flex cursor-pointer items-center gap-2 rounded-lg border bg-card px-3 py-2 text-sm font-medium"
                >
                  <Checkbox
                    checked={preparedBuckets.has(bucket)}
                    disabled={pending}
                    onCheckedChange={(checked) =>
                      setPreparedBuckets((old) => {
                        const next = new Set(old);
                        if (checked) next.add(bucket);
                        else next.delete(bucket);
                        return next;
                      })
                    }
                  />
                  {bucket}
                </label>
              ))}
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <select
                value={prepareYears}
                onChange={(event) =>
                  setPrepareYears(Number(event.target.value) as 2 | 5 | 10)
                }
                className="h-9 rounded-lg border bg-background px-3 text-sm"
                disabled={pending}
              >
                <option value={2}>Prepare for 2 years</option>
                <option value={5}>Prepare for 5 years</option>
                <option value={10}>Prepare for 10 years</option>
              </select>
              <Button
                disabled={!preparedBuckets.size || pending}
                onClick={() => void prepareFolders()}
              >
                <FolderPlus />
                Prepare {preparedBuckets.size || ''} categories
              </Button>
              <span className="text-xs text-muted-foreground">
                Includes the current year plus the selected number of future
                years.
              </span>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              disabled={!selected.size || pending}
              onClick={() => void apply()}
            >
              <FolderPlus />
              Create folders + file selected
            </Button>
            <Button
              variant="outline"
              disabled={!rules.some((rule) => rule.enabled) || pending}
              onClick={() => void applySavedRules()}
            >
              <FolderInput />
              Apply active rules
            </Button>
            <Button
              variant="outline"
              disabled={!proposals.length || pending}
              onClick={() =>
                setSelected(
                  new Set(proposals.slice(0, 25).map((item) => item.id)),
                )
              }
            >
              Select top proposals
            </Button>
            <Button
              variant="ghost"
              disabled={!selected.size || pending}
              onClick={() => setSelected(new Set())}
            >
              Clear
            </Button>
            <label className="ml-auto flex items-center gap-2 text-sm font-medium">
              Prepare future years
              <select
                value={futureYears}
                onChange={(event) =>
                  setFutureYears(Number(event.target.value) as 0 | 2 | 5 | 10)
                }
                className="h-9 rounded-lg border bg-background px-3 text-sm"
                disabled={pending}
              >
                <option value={0}>None</option>
                <option value={2}>Next 2 years</option>
                <option value={5}>Next 5 years</option>
                <option value={10}>Next 10 years</option>
              </select>
            </label>
          </div>
          <p className="mt-3 text-xs text-muted-foreground">
            {selected.size} folders selected · {messages.toLocaleString()}{' '}
            existing messages. Active category rules dynamically use the year of
            each message. This action organizes mail only; it never deletes or
            exports it.
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
            <AlertTitle>Filing completed</AlertTitle>
            <AlertDescription>{message}</AlertDescription>
          </Alert>
        )}
        <section className="panel mt-4 overflow-x-auto">
          <div className="mb-4">
            <p className="text-sm font-semibold">Suggested folders</p>
            <p className="text-xs text-muted-foreground">
              Derived from the latest completed AI Cleanup analysis.
            </p>
          </div>
          <TableFilterBar
            value={query}
            onChange={setQuery}
            shown={visibleProposals.length}
            total={proposals.length}
            placeholder="Filter destinations, years, or reasons…"
          />
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10" />
                <SortableTableHead
                  label="Destination"
                  sortKey="destination"
                  activeKey={sort.key}
                  direction={sort.direction}
                  onSort={changeSort}
                />
                <SortableTableHead
                  label="Why"
                  sortKey="why"
                  activeKey={sort.key}
                  direction={sort.direction}
                  onSort={changeSort}
                />
                <SortableTableHead
                  label="Messages"
                  sortKey="messages"
                  activeKey={sort.key}
                  direction={sort.direction}
                  onSort={changeSort}
                  className="text-right"
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
              {visibleProposals.map((item) => (
                <TableRow key={item.id}>
                  <TableCell>
                    <Checkbox
                      disabled={pending}
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
                  <TableCell>
                    <p className="flex items-center gap-2 font-semibold">
                      <FolderInput size={16} />
                      {item.destination}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {item.bucket} · {item.year}
                    </p>
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground">
                    {item.reason}
                  </TableCell>
                  <TableCell className="text-right font-semibold">
                    {item.message_count.toLocaleString()}
                  </TableCell>
                  <TableCell className="text-right">
                    {formatBytes(item.total_bytes)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {!proposals.length && (
            <p className="py-8 text-center text-sm text-muted-foreground">
              No new filing proposals remain for the latest analysis.
            </p>
          )}
        </section>
        <section className="panel mt-4">
          <div className="mb-4">
            <p className="text-sm font-semibold">Saved organizer rules</p>
            <p className="text-xs text-muted-foreground">
              Active rules are retained locally for subsequent organizer runs.
              Provider-specific server filters are not required.
            </p>
          </div>
          <div className="space-y-2">
            {rules.map((rule) => (
              <div
                key={rule.id}
                className="flex flex-wrap items-center gap-3 rounded-xl border p-3"
              >
                <span className="grid size-9 place-items-center rounded-lg bg-secondary">
                  <FolderInput size={17} />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-semibold">
                    {rule.destination}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {rule.bucket} messages from {rule.target_year}
                  </p>
                </div>
                <Badge variant={rule.enabled ? 'default' : 'secondary'}>
                  {rule.enabled ? 'active' : 'paused'}
                </Badge>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={pending}
                  onClick={() => void toggle(rule)}
                >
                  <Power />
                  {rule.enabled ? 'Pause' : 'Enable'}
                </Button>
              </div>
            ))}
            {!rules.length && (
              <p className="text-sm text-muted-foreground">
                No filing rules have been approved yet.
              </p>
            )}
          </div>
        </section>
      </div>
    </main>
  );
}
