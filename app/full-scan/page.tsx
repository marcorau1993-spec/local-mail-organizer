'use client';

import { useCallback, useEffect, useState } from 'react';
import type { SyntheticEvent } from 'react';
import Link from 'next/link';
import {
  ArrowLeft,
  Archive,
  Database,
  FolderOpen,
  HardDrive,
  Loader2,
  MailCheck,
  Pause,
  Play,
  RefreshCw,
  ShieldCheck,
} from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Progress,
  ProgressLabel,
  ProgressValue,
} from '@/components/ui/progress';
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
type FolderProgress = {
  name: string;
  total_messages: number;
  processed_messages: number;
  completed: number;
};
type ScanStatus = {
  job_id: string;
  status: string;
  current_folder?: string;
  total_messages: number;
  processed_messages: number;
  progress_percent: number;
  total_bytes: number;
  large_messages: number;
  newsletter_messages: number;
  error?: string;
  folders?: FolderProgress[];
};
type PlanGroup = {
  sender: string;
  sender_domain: string;
  list_id: string;
  message_count: number;
  total_bytes: number;
  unsubscribe_count: number;
  large_count: number;
  recommendation: string;
};

const activeStates = new Set(['queued', 'connecting', 'inventory', 'pausing']);
function formatBytes(value: number) {
  if (value < 1_048_576) return `${Math.round(value / 1024)} KB`;
  return `${(value / 1_048_576).toFixed(1)} MB`;
}
function title(value: string) {
  return value
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export default function FullScanPage() {
  const [provider, setProvider] = useState('webde');
  const [username, setUsername] = useState('');
  const [status, setStatus] = useState<ScanStatus | null>(null);
  const [groups, setGroups] = useState<PlanGroup[]>([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState<{ key: string; direction: SortDirection }>({
    key: 'messages',
    direction: 'desc',
  });
  const planGroups = filterAndSort(
    groups,
    query,
    (group) =>
      `${group.sender} ${group.sender_domain} ${group.list_id} ${group.recommendation}`,
    (group) =>
      sort.key === 'sender'
        ? group.sender
        : sort.key === 'messages'
          ? group.message_count
          : sort.key === 'size'
            ? group.total_bytes
            : sort.key === 'signals'
              ? group.unsubscribe_count + group.large_count
              : group.recommendation,
    sort.direction,
  );
  const changeSort = (key: string) =>
    setSort((old) => nextSort(old.key, old.direction, key));

  const refresh = useCallback(async (jobId: string) => {
    const response = await fetch(`${API_URL}/api/full-scan/${jobId}`);
    const payload = (await response.json()) as ScanStatus & { detail?: string };
    if (!response.ok)
      throw new Error(payload.detail || 'Unable to read scan status');
    setStatus(payload);
    setError(payload.status === 'failed' ? payload.error || 'Scan failed' : '');
    if (payload.status === 'completed') {
      const planResponse = await fetch(
        `${API_URL}/api/full-scan/${jobId}/plan`,
      );
      const plan = (await planResponse.json()) as { groups?: PlanGroup[] };
      setGroups(plan.groups ?? []);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const selected = new URLSearchParams(window.location.search).get(
        'provider',
      );
      if (selected) setProvider(selected);
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (!status || !activeStates.has(status.status)) return;
    const timer = window.setInterval(() => {
      void refresh(status.job_id).catch((reason) =>
        setError(
          reason instanceof Error ? reason.message : 'Status refresh failed',
        ),
      );
    }, 1500);
    return () => window.clearInterval(timer);
  }, [refresh, status]);

  async function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    await request('/api/full-scan/start');
  }
  async function request(path: string) {
    setPending(true);
    setError('');
    try {
      const response = await fetch(`${API_URL}${path}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider, username }),
      });
      const payload = (await response.json()) as ScanStatus & {
        detail?: string;
      };
      if (!response.ok) throw new Error(payload.detail || 'Request failed');
      setStatus(payload);
      setError(
        payload.status === 'failed' ? payload.error || 'Scan failed' : '',
      );
      if (payload.job_id) await refresh(payload.job_id);
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
  async function control(action: 'pause' | 'resume') {
    if (!status) return;
    setPending(true);
    try {
      const response = await fetch(
        `${API_URL}/api/full-scan/${status.job_id}/${action}`,
        { method: 'POST' },
      );
      if (!response.ok) throw new Error(`Could not ${action} scan`);
      await refresh(status.job_id);
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : 'Control request failed',
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
            <p className="eyebrow">Complete mailbox intelligence</p>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight">
              Organize the whole mailbox.
            </h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
              Every selectable folder is inventoried in resumable batches. The
              first full run builds a safe action plan without changing a single
              message.
            </p>
          </div>
          <Badge
            variant="outline"
            className="h-7 border-safe/30 bg-safe-soft px-3 text-safe"
          >
            <ShieldCheck /> Read-only inventory
          </Badge>
        </div>
        <div className="mt-6 grid gap-5 lg:grid-cols-[340px_minmax(0,1fr)]">
          <aside className="space-y-5">
            <form className="panel space-y-4" onSubmit={submit}>
              <div className="flex items-center gap-2 font-semibold">
                <Database className="text-brand" size={18} /> Mailbox source
              </div>
              <label htmlFor="scan-account" className="text-sm font-semibold">
                Account provider
              </label>
              <select
                value={provider}
                onChange={(event) => setProvider(event.target.value)}
                className="h-10 w-full rounded-lg border bg-background px-3 text-sm"
              >
                <option value="webde">WEB.DE</option>
                <option value="gmx">GMX</option>
                <option value="gmail">Gmail / Google Workspace</option>
                <option value="yahoo">Yahoo Mail</option>
                <option value="icloud">iCloud Mail</option>
                <option value="aol">AOL Mail</option>
                <option value="fastmail">Fastmail</option>
                <option value="mailbox_org">mailbox.org</option>
                <option value="posteo">Posteo</option>
                <option value="zoho">Zoho Mail</option>
                <option value="t_online">Telekom / T-Online</option>
              </select>
              <label htmlFor="scan-account" className="text-sm font-semibold">
                Email address or username
              </label>
              <Input
                id="scan-account"
                inputMode="email"
                autoComplete="username"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                placeholder="account@web.de"
                required
                className="h-10"
              />
              <Button
                type="submit"
                disabled={
                  pending ||
                  !username ||
                  Boolean(status && activeStates.has(status.status))
                }
                className="h-10 w-full"
              >
                {pending ? <Loader2 className="animate-spin" /> : <Play />}Start
                complete scan
              </Button>
              <Button
                type="button"
                variant="outline"
                disabled={pending || !username}
                className="h-9 w-full"
                onClick={() => void request('/api/full-scan/latest')}
              >
                <RefreshCw />
                Find latest scan
              </Button>
              <p className="text-xs leading-5 text-muted-foreground">
                Credentials must have been saved during account setup. Your
                address is not stored in the project database.
              </p>
            </form>
            {status && (
              <div className="panel space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-semibold">Scan controls</span>
                  <Badge variant="secondary">{title(status.status)}</Badge>
                </div>
                {activeStates.has(status.status) && (
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => void control('pause')}
                    disabled={pending}
                    className="w-full"
                  >
                    <Pause />
                    Pause safely
                  </Button>
                )}
                {['paused', 'failed'].includes(status.status) && (
                  <Button
                    type="button"
                    onClick={() => void control('resume')}
                    disabled={pending}
                    className="w-full"
                  >
                    <Play />
                    Resume scan
                  </Button>
                )}
              </div>
            )}
          </aside>
          <section className="min-w-0 space-y-5">
            {error && (
              <Alert variant="destructive">
                <AlertTitle>Scan stopped safely</AlertTitle>
                <AlertDescription>
                  {error}. No mailbox changes were made.
                </AlertDescription>
              </Alert>
            )}
            {!status && !error && (
              <div className="panel grid min-h-[360px] place-items-center text-center">
                <div>
                  <span className="mx-auto grid size-14 place-items-center rounded-2xl bg-secondary text-brand">
                    <MailCheck size={25} />
                  </span>
                  <h2 className="mt-4 text-lg font-semibold">
                    Ready to inventory every folder
                  </h2>
                  <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-muted-foreground">
                    The scan can be paused and resumed. Header data and progress
                    stay in a private local database excluded from Git.
                  </p>
                </div>
              </div>
            )}
            {status && (
              <>
                <div className="panel">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <p className="eyebrow">Current run</p>
                      <h2 className="mt-1 text-lg font-semibold">
                        {status.current_folder
                          ? `Scanning ${status.current_folder}`
                          : title(status.status)}
                      </h2>
                    </div>
                    <span className="text-sm font-semibold tabular-nums">
                      {status.processed_messages.toLocaleString()} /{' '}
                      {status.total_messages.toLocaleString()}
                    </span>
                  </div>
                  <Progress value={status.progress_percent} className="mt-5">
                    <ProgressLabel>Mailbox progress</ProgressLabel>
                    <ProgressValue>
                      {() => `${status.progress_percent}%`}
                    </ProgressValue>
                  </Progress>
                  <div className="mt-5 grid gap-3 sm:grid-cols-3">
                    <Metric
                      icon={Database}
                      label="Indexed"
                      value={status.processed_messages.toLocaleString()}
                    />
                    <Metric
                      icon={Archive}
                      label="Newsletters"
                      value={status.newsletter_messages.toLocaleString()}
                    />
                    <Metric
                      icon={HardDrive}
                      label="Large messages"
                      value={status.large_messages.toLocaleString()}
                    />
                  </div>
                  <p className="mt-4 text-xs text-muted-foreground">
                    Indexed size: {formatBytes(status.total_bytes)}
                  </p>
                </div>
                {status.folders && status.folders.length > 0 && (
                  <div className="panel">
                    <h2 className="font-semibold">Folder progress</h2>
                    <div className="mt-4 grid gap-2 sm:grid-cols-2">
                      {status.folders.map((folder) => (
                        <div
                          key={folder.name}
                          className="flex items-center gap-3 rounded-xl border p-3"
                        >
                          <FolderOpen
                            size={16}
                            className={
                              folder.completed ? 'text-safe' : 'text-brand'
                            }
                          />
                          <span className="min-w-0 flex-1 truncate text-sm font-medium">
                            {folder.name}
                          </span>
                          <span className="text-xs tabular-nums text-muted-foreground">
                            {folder.processed_messages}/{folder.total_messages}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {status.status === 'completed' && (
                  <div className="panel">
                    <div className="mb-4 flex items-center justify-between">
                      <div>
                        <p className="eyebrow">Proposed action groups</p>
                        <h2 className="mt-1 text-lg font-semibold">
                          {groups.length} sender and list groups
                        </h2>
                      </div>
                      <Badge variant="outline">Preview only</Badge>
                    </div>
                    <TableFilterBar
                      value={query}
                      onChange={setQuery}
                      shown={planGroups.length}
                      total={groups.length}
                      placeholder="Filter senders, lists, or proposals…"
                    />
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <SortableTableHead
                            label="Sender / list"
                            sortKey="sender"
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
                          />
                          <SortableTableHead
                            label="Size"
                            sortKey="size"
                            activeKey={sort.key}
                            direction={sort.direction}
                            onSort={changeSort}
                          />
                          <SortableTableHead
                            label="Signals"
                            sortKey="signals"
                            activeKey={sort.key}
                            direction={sort.direction}
                            onSort={changeSort}
                          />
                          <SortableTableHead
                            label="Proposal"
                            sortKey="proposal"
                            activeKey={sort.key}
                            direction={sort.direction}
                            onSort={changeSort}
                          />
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {planGroups.map((group, index) => (
                          <TableRow
                            key={`${group.sender}-${group.list_id}-${index}`}
                          >
                            <TableCell className="max-w-[340px] whitespace-normal">
                              <p className="truncate font-semibold">
                                {group.sender}
                              </p>
                              <p className="truncate text-xs text-muted-foreground">
                                {group.list_id || group.sender_domain}
                              </p>
                            </TableCell>
                            <TableCell>{group.message_count}</TableCell>
                            <TableCell>
                              {formatBytes(group.total_bytes)}
                            </TableCell>
                            <TableCell>
                              <span className="text-xs text-muted-foreground">
                                {group.unsubscribe_count
                                  ? `${group.unsubscribe_count} unsubscribe headers`
                                  : ''}
                                {group.large_count
                                  ? ` · ${group.large_count} large`
                                  : ''}
                              </span>
                            </TableCell>
                            <TableCell>
                              <Badge variant="secondary">
                                {title(group.recommendation)}
                              </Badge>
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                    <div className="mt-5 rounded-xl border bg-secondary/30 p-4 text-sm text-muted-foreground">
                      <strong className="text-foreground">Safety gate:</strong>{' '}
                      this plan contains no executable delete, unsubscribe, or
                      move control. Those actions will be enabled only after
                      this complete inventory has been reviewed.
                    </div>
                  </div>
                )}
              </>
            )}
          </section>
        </div>
      </div>
    </main>
  );
}

function Metric({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Database;
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-xl border bg-secondary/20 p-4">
      <Icon size={17} className="text-brand" />
      <p className="mt-3 text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-xl font-semibold">{value}</p>
    </div>
  );
}
