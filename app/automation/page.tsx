'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import {
  ArrowLeft,
  Bot,
  CircleCheck,
  Clock3,
  Play,
  RefreshCw,
  ShieldAlert,
  Unplug,
} from 'lucide-react';
import {
  AccountSwitcher,
  useAccountSelection,
} from '@/components/account-switcher';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
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

type Preferences = {
  paused: number;
  learning_mode: number;
  schedule_minutes: number;
  max_actions: number;
  notify_errors: number;
};
type AutomationRun = {
  id: string;
  trigger: string;
  status: string;
  processed: number;
  moved: number;
  deferred: number;
  started_at: string;
  finished_at?: string;
  error?: string;
};
type AutomationStatus = {
  processed: number;
  moved: number;
  no_match: number;
  last_activity?: string;
  active_rules: number;
  latest_run?: AutomationRun;
  runs: AutomationRun[];
  preferences: Preferences;
  windows_task: {
    supported: boolean;
    installed: boolean;
    state: string;
    last_run_time?: string;
    last_result?: number;
  };
};

export default function AutomationPage() {
  const { accounts, accountId, setAccountId } = useAccountSelection();
  const [status, setStatus] = useState<AutomationStatus | null>(null);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [pending, setPending] = useState(false);

  const load = useCallback(async () => {
    if (!accountId) return;
    const response = await fetch(
      `${API_URL}/api/automation/status?account_id=${encodeURIComponent(accountId)}`,
      { cache: 'no-store' },
    );
    const payload = (await response.json()) as AutomationStatus & {
      detail?: string;
    };
    if (!response.ok)
      throw new Error(payload.detail || 'Automation status is unavailable');
    setStatus(payload);
  }, [accountId]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setError('');
      setMessage('');
      void load().catch((reason) =>
        setError(reason instanceof Error ? reason.message : 'Status failed'),
      );
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  useEffect(() => {
    if (status?.latest_run?.status !== 'running') return;
    const timer = window.setInterval(() => void load(), 1500);
    return () => window.clearInterval(timer);
  }, [load, status?.latest_run?.status]);

  const blockedReason = useMemo(() => {
    if (!status) return 'Loading automation status';
    if (status.latest_run?.status === 'running') return 'A run is already active';
    if (status.preferences.paused) return 'This account is paused';
    if (status.preferences.learning_mode)
      return 'Learning mode prevents automatic moves';
    if (!status.active_rules) return 'No approved filing rules are active';
    return '';
  }, [status]);

  async function savePreferences(next: Preferences) {
    if (!accountId) return;
    setStatus((current) =>
      current ? { ...current, preferences: next } : current,
    );
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
    if (!response.ok) setError('Automation preferences could not be saved');
    else setMessage('Automation preferences saved');
    await load();
  }

  async function runNow() {
    if (!accountId || blockedReason) return;
    if (
      !window.confirm(
        `Run the approved local filing rules now? Up to ${status?.preferences.max_actions ?? 0} new INBOX messages may be moved into prepared folders.`,
      )
    )
      return;
    setPending(true);
    setError('');
    setMessage('');
    try {
      const response = await fetch(`${API_URL}/api/automation/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ account_id: accountId, confirmed: true }),
      });
      const payload = (await response.json()) as { detail?: string };
      if (!response.ok)
        throw new Error(payload.detail || 'Automation run could not start');
      setMessage('Automation run started. Progress updates automatically.');
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Automation failed');
    } finally {
      setPending(false);
    }
  }

  async function configureTask(mode: 'install' | 'uninstall') {
    const verb = mode === 'install' ? 'install and start' : 'remove';
    if (!window.confirm(`${verb} the Local Mail Organizer Windows task?`)) return;
    setPending(true);
    setError('');
    try {
      const response = await fetch(`${API_URL}/api/automation/windows-task`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode, confirmed: true }),
      });
      const payload = (await response.json()) as { detail?: string };
      if (!response.ok)
        throw new Error(payload.detail || 'Windows task could not be updated');
      setMessage(
        mode === 'install'
          ? 'Windows background task installed and started'
          : 'Windows background task removed; rules and history were retained',
      );
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Task update failed');
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
            <p className="eyebrow">Mailbox automation</p>
            <h1 className="mt-2 text-3xl font-semibold">Automation Center</h1>
            <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
              Run approved filing rules in the background, inspect every run,
              and control each mailbox independently.
            </p>
            <AccountSwitcher
              accounts={accounts}
              accountId={accountId}
              onChange={setAccountId}
              className="mt-4"
            />
          </div>
          <Button
            onClick={() => void runNow()}
            disabled={pending || Boolean(blockedReason)}
            title={blockedReason}
          >
            {status?.latest_run?.status === 'running' ? (
              <RefreshCw className="animate-spin" />
            ) : (
              <Play />
            )}
            Run now
          </Button>
        </div>

        {error && (
          <Alert variant="destructive" className="mt-5">
            <AlertTitle>Stopped safely</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {message && (
          <Alert className="mt-5">
            <AlertTitle>Automation updated</AlertTitle>
            <AlertDescription>{message}</AlertDescription>
          </Alert>
        )}

        <div className="mt-6 grid gap-5 lg:grid-cols-[1.1fr_0.9fr]">
          <section className="panel">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="flex items-center gap-2 text-lg font-semibold">
                  <Bot size={19} /> Windows background agent
                </h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  Runs locally in your signed-in Windows account. Credentials
                  remain in Windows Credential Manager.
                </p>
              </div>
              <span className="rounded-full border px-3 py-1 text-xs font-semibold">
                {status?.windows_task.installed
                  ? status.windows_task.state
                  : 'Not installed'}
              </span>
            </div>
            <div className="mt-5 flex flex-wrap gap-2">
              {!status?.windows_task.installed ? (
                <Button
                  variant="outline"
                  disabled={pending || !status?.windows_task.supported}
                  onClick={() => void configureTask('install')}
                >
                  <CircleCheck /> Install background task
                </Button>
              ) : (
                <Button
                  variant="outline"
                  disabled={pending}
                  onClick={() => void configureTask('uninstall')}
                >
                  <Unplug /> Remove background task
                </Button>
              )}
            </div>
            <div className="mt-5 rounded-xl border border-warning/30 bg-warning-soft p-4 text-sm">
              <div className="flex gap-3">
                <ShieldAlert className="mt-0.5 shrink-0" size={18} />
                <p>
                  These are local mailbox rules applied through IMAP. They are
                  not native WEB.DE or GMX web-portal filters because standard
                  IMAP cannot create provider-side filtering rules.
                </p>
              </div>
            </div>
          </section>

          <section className="panel">
            <h2 className="flex items-center gap-2 text-lg font-semibold">
              <Clock3 size={19} /> Account schedule
            </h2>
            {status && (
              <div className="mt-4 grid gap-4 sm:grid-cols-2">
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={Boolean(status.preferences.learning_mode)}
                    onChange={(event) =>
                      void savePreferences({
                        ...status.preferences,
                        learning_mode: Number(event.target.checked),
                      })
                    }
                  />
                  Learning mode
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={Boolean(status.preferences.paused)}
                    onChange={(event) =>
                      void savePreferences({
                        ...status.preferences,
                        paused: Number(event.target.checked),
                      })
                    }
                  />
                  Pause this mailbox
                </label>
                <label className="text-sm" htmlFor="automation-interval">
                  Interval in minutes
                  <Input
                    id="automation-interval"
                    type="number"
                    min={1}
                    max={1440}
                    value={status.preferences.schedule_minutes}
                    onChange={(event) =>
                      setStatus({
                        ...status,
                        preferences: {
                          ...status.preferences,
                          schedule_minutes: Number(event.target.value),
                        },
                      })
                    }
                    onBlur={() => void savePreferences(status.preferences)}
                  />
                </label>
                <label className="text-sm" htmlFor="automation-limit">
                  Maximum moves per run
                  <Input
                    id="automation-limit"
                    type="number"
                    min={1}
                    max={100}
                    value={status.preferences.max_actions}
                    onChange={(event) =>
                      setStatus({
                        ...status,
                        preferences: {
                          ...status.preferences,
                          max_actions: Number(event.target.value),
                        },
                      })
                    }
                    onBlur={() => void savePreferences(status.preferences)}
                  />
                </label>
              </div>
            )}
            {blockedReason && (
              <p className="mt-4 text-xs text-warning">{blockedReason}</p>
            )}
          </section>
        </div>

        <div className="mt-5 grid gap-4 sm:grid-cols-4">
          <Metric label="Active rules" value={status?.active_rules ?? 0} />
          <Metric label="Messages checked" value={status?.processed ?? 0} />
          <Metric label="Messages filed" value={status?.moved ?? 0} />
          <Metric label="No rule matched" value={status?.no_match ?? 0} />
        </div>

        <section className="panel mt-5 overflow-x-auto">
          <h2 className="text-lg font-semibold">Run history</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Durable account-local history. Error text is redacted and contains
            no credentials or message content.
          </p>
          <Table className="mt-4">
            <TableHeader>
              <TableRow>
                <TableHead>Started</TableHead>
                <TableHead>Trigger</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Checked</TableHead>
                <TableHead className="text-right">Moved</TableHead>
                <TableHead className="text-right">Deferred</TableHead>
                <TableHead>Detail</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(status?.runs ?? []).map((run) => (
                <TableRow key={run.id}>
                  <TableCell>{new Date(run.started_at).toLocaleString()}</TableCell>
                  <TableCell>{run.trigger}</TableCell>
                  <TableCell>{run.status}</TableCell>
                  <TableCell className="text-right">{run.processed}</TableCell>
                  <TableCell className="text-right">{run.moved}</TableCell>
                  <TableCell className="text-right">{run.deferred}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {run.error || '—'}
                  </TableCell>
                </TableRow>
              ))}
              {!status?.runs.length && (
                <TableRow>
                  <TableCell colSpan={7} className="py-10 text-center text-muted-foreground">
                    No automation run has been recorded for this mailbox yet.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </section>
      </div>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="panel">
      <div className="text-2xl font-semibold">{value.toLocaleString()}</div>
      <div className="mt-1 text-xs text-muted-foreground">{label}</div>
    </div>
  );
}
