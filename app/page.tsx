'use client';

import { useCallback, useEffect, useState } from 'react';
import type { SyntheticEvent } from 'react';
import {
  Archive,
  Box,
  CheckCircle2,
  ChevronRight,
  HardDrive,
  Inbox,
  LockKeyhole,
  MailCheck,
  Network,
  ScanSearch,
  ShieldCheck,
  ShieldAlert,
  Sparkles,
  MailMinus,
  FolderTree,
  Trash2,
  SlidersHorizontal,
  Megaphone,
} from 'lucide-react';
import Link from 'next/link';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  AccountSwitcher,
  useAccountSelection,
} from '@/components/account-switcher';

const API_URL = 'http://127.0.0.1:8765';
type DashboardData = {
  connected_accounts: number;
  latest_scan: {
    job_id: string;
    status: string;
    processed_messages: number;
    total_messages: number;
    total_bytes: number;
    large_messages: number;
    newsletter_messages: number;
    updated_at: string;
  } | null;
  potential_space_saved: number;
  archive: {
    kind: string;
    root_path: string;
    verified_at: string;
  } | null;
};

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1_048_576) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1_073_741_824) return `${(value / 1_048_576).toFixed(1)} MB`;
  return `${(value / 1_073_741_824).toFixed(1)} GB`;
}

const steps = [
  ['Connect account', 'WEB.DE via IMAP'],
  ['Scan safely', 'Read-only metadata pass'],
  ['Review plan', 'Nothing changes without approval'],
];

export default function Home() {
  const { accounts, accountId, setAccountId } = useAccountSelection();
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [archivePath, setArchivePath] = useState('');
  const [archivePending, setArchivePending] = useState(false);
  const [archiveMessage, setArchiveMessage] = useState('');
  const [error, setError] = useState('');
  const [trashPending, setTrashPending] = useState(false);
  const [trashCount, setTrashCount] = useState<number | null>(null);
  const [trashMessage, setTrashMessage] = useState('');

  const loadDashboard = useCallback(async () => {
    if (!accountId) {
      setDashboard(null);
      return;
    }
    const response = await fetch(
      `${API_URL}/api/dashboard?account_id=${encodeURIComponent(accountId)}`,
      {
        cache: 'no-store',
      },
    );
    if (!response.ok) throw new Error('The local API is unavailable');
    const payload = (await response.json()) as DashboardData;
    setDashboard(payload);
    setArchivePath(payload.archive?.kind === 'local_nas' ? payload.archive.root_path : '');
    const trashResponse = await fetch(
      `${API_URL}/api/mail/trash/status?account_id=${encodeURIComponent(accountId)}`,
      { cache: 'no-store' },
    );
    setTrashCount(
      trashResponse.ok
        ? ((await trashResponse.json()) as { count: number }).count
        : null,
    );
  }, [accountId]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setTrashMessage('');
      setArchiveMessage('');
      void loadDashboard().catch((reason) =>
        setError(reason instanceof Error ? reason.message : 'Dashboard failed'),
      );
    }, 0);
    return () => window.clearTimeout(timer);
  }, [loadDashboard]);

  async function configureArchive(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    setArchivePending(true);
    setArchiveMessage('');
    setError('');
    try {
      const response = await fetch(`${API_URL}/api/archive/destination`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          account_id: accountId,
          kind: 'local_nas',
          root_path: archivePath,
        }),
      });
      const payload = (await response.json()) as { detail?: string };
      if (!response.ok)
        throw new Error(payload.detail || 'Archive verification failed');
      setArchiveMessage('Storage verified and saved');
      await loadDashboard();
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : 'Archive setup failed',
      );
    } finally {
      setArchivePending(false);
    }
  }

  async function emptyTrash() {
    const confirmation = window.prompt(
      `This permanently deletes ${trashCount?.toLocaleString() ?? 'all'} message(s) from Trash in the selected mailbox. Type EMPTY TRASH to continue.`,
    );
    if (confirmation !== 'EMPTY TRASH') return;
    setTrashPending(true);
    setTrashMessage('');
    setError('');
    try {
      const response = await fetch(`${API_URL}/api/mail/trash/empty`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ account_id: accountId, confirmation }),
      });
      const payload = (await response.json()) as {
        deleted?: number;
        detail?: string;
      };
      if (!response.ok)
        throw new Error(payload.detail || 'Trash cleanup stopped safely');
      setTrashMessage(
        `${payload.deleted ?? 0} messages permanently removed from Trash`,
      );
      setTrashCount(0);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : 'Trash cleanup stopped safely',
      );
    } finally {
      setTrashPending(false);
    }
  }

  const scan = dashboard?.latest_scan;
  const connected = dashboard?.connected_accounts ?? 0;
  const setupComplete =
    (connected > 0 ? 1 : 0) +
    (scan?.status === 'completed' ? 1 : 0) +
    (scan?.status === 'completed' ? 1 : 0);

  return (
    <main className="min-h-screen bg-background text-foreground">
      <header className="border-b bg-card/90">
        <div className="mx-auto flex max-w-[1440px] items-center justify-between px-5 py-4 lg:px-8">
          <div className="flex items-center gap-3">
            <div className="grid size-10 place-items-center rounded-xl bg-primary text-primary-foreground">
              <MailCheck size={20} />
            </div>
            <div>
              <p className="text-sm font-semibold">Local Mail Organizer</p>
              <p className="text-xs text-muted-foreground">
                Private inbox intelligence
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 rounded-full border border-safe/25 bg-safe-soft px-3 py-1.5 text-xs font-semibold text-safe">
            <LockKeyhole size={14} /> Local-only mode
          </div>
        </div>
      </header>
      <div className="mx-auto grid max-w-[1440px] gap-6 px-5 py-6 lg:grid-cols-[220px_minmax(0,1fr)] lg:px-8">
        <aside className="hidden lg:block">
          <nav className="space-y-1">
            <a className="nav-item nav-active" href="#overview">
              <Inbox size={17} /> Overview
            </a>
            <Link className="nav-item" href="/full-scan">
              <ScanSearch size={17} /> Full mailbox scan
            </Link>
            <p className="eyebrow px-3 pb-1 pt-5">Standard</p>
            <Link className="nav-item" href="/biggest">
              <Archive size={17} /> Biggest mails
            </Link>
            <Link className="nav-item" href="/senders">
              <Inbox size={17} /> Top senders
            </Link>
            <Link className="nav-item" href="/sent-mail">
              <MailCheck size={17} /> Sent mail
            </Link>
            <Link className="nav-item" href="/newsletters">
              <MailMinus size={17} /> Newsletters
            </Link>
            <Link className="nav-item" href="/control-center">
              <SlidersHorizontal size={17} /> Control Center
            </Link>
            <Link className="nav-item" href="/mailbox-health">
              <Network size={17} /> Mailbox Health
            </Link>
            <Link className="nav-item" href="/archive">
              <Archive size={17} /> Archive storage
            </Link>
            <a className="nav-item" href="#safety">
              <ShieldCheck size={17} /> Safety rules
            </a>
            <p className="eyebrow px-3 pb-1 pt-5">AI functions</p>
            <Link className="nav-item" href="/action-inbox">
              <CheckCircle2 size={17} /> Action Inbox
            </Link>
            <Link className="nav-item" href="/smart-search">
              <ScanSearch size={17} /> Smart Search
            </Link>
            <Link className="nav-item" href="/ai-cleanup">
              <Sparkles size={17} /> AI Cleanup
            </Link>
            <Link className="nav-item" href="/documents">
              <Box size={17} /> Documents & lifecycle
            </Link>
            <Link className="nav-item" href="/relationships">
              <Network size={17} /> Companies & relationships
            </Link>
            <Link className="nav-item" href="/promotions">
              <Megaphone size={17} /> Promotions & Clutter
            </Link>
            <Link className="nav-item" href="/security">
              <ShieldAlert size={17} /> Spam & phishing
            </Link>
            <Link className="nav-item" href="/filing-plan">
              <FolderTree size={17} /> AI Filing plan
            </Link>
            <Link className="nav-item" href="/ai-quality">
              <Sparkles size={17} /> AI Quality Center
            </Link>
          </nav>
          <div className="mt-8 rounded-xl border bg-card p-4">
            <p className="eyebrow">AI engine</p>
            <div className="mt-3 flex items-center gap-2 text-sm font-medium">
              <Sparkles className="text-brand" size={16} /> Qwen 3.5 · 9B
            </div>
            <p className="mt-2 text-xs leading-5 text-muted-foreground">
              Runs through your local Ollama instance. Mail content never goes
              to a hosted model.
            </p>
          </div>
        </aside>
        <section id="overview" className="min-w-0">
          <div className="mb-6 flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
            <div>
              <p className="eyebrow">Workspace overview</p>
              <h1 className="mt-2 text-3xl font-semibold tracking-[-0.035em] sm:text-4xl">
                Your inbox, under control.
              </h1>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
                Start with a private read-only scan. Every suggested move,
                archive, unsubscribe, or deletion remains reviewable.
              </p>
              <AccountSwitcher
                accounts={accounts}
                accountId={accountId}
                onChange={setAccountId}
                className="mt-4"
              />
              <Button
                variant="destructive"
                className="ml-2 mt-4"
                disabled={!accountId || trashPending}
                onClick={() => void emptyTrash()}
              >
                <Trash2 />{' '}
                {trashPending
                  ? 'Emptying Trash…'
                  : `Empty Trash${trashCount === null ? '' : ` (${trashCount.toLocaleString()})`}`}
              </Button>
              {trashMessage && (
                <Alert className="mt-3 max-w-xl">
                  <AlertTitle>Trash emptied</AlertTitle>
                  <AlertDescription>{trashMessage}</AlertDescription>
                </Alert>
              )}
            </div>
            <span className="inline-flex w-fit items-center gap-2 rounded-lg border border-warning/25 bg-warning-soft px-3 py-2 text-xs font-semibold text-warning">
              <ShieldCheck size={15} /> Explicit approval required
            </span>
          </div>
          <div className="grid gap-4 md:grid-cols-3">
            <article className="metric-card">
              <Network className="metric-icon" />
              <p className="metric-label">Connected accounts</p>
              <p className="metric-value">{dashboard ? connected : '—'}</p>
              <p className="metric-note">
                {connected
                  ? 'WEB.DE connected securely'
                  : 'No account connected'}
              </p>
            </article>
            <article className="metric-card">
              <ScanSearch className="metric-icon" />
              <p className="metric-label">Messages analyzed</p>
              <p className="metric-value">
                {scan ? scan.processed_messages.toLocaleString() : '—'}
              </p>
              <p className="metric-note">
                {scan?.status === 'completed'
                  ? `${scan.newsletter_messages.toLocaleString()} newsletter messages detected`
                  : 'Waiting for first safe scan'}
              </p>
            </article>
            <article className="metric-card">
              <Archive className="metric-icon" />
              <p className="metric-label">Potential space saved</p>
              <p className="metric-value">
                {dashboard ? formatBytes(dashboard.potential_space_saved) : '—'}
              </p>
              <p className="metric-note">
                {scan
                  ? `${scan.large_messages.toLocaleString()} archive candidates`
                  : 'Large mail detection enabled'}
              </p>
            </article>
          </div>
          {error && (
            <Alert variant="destructive" className="mt-5">
              <AlertTitle>Action could not be completed</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          <div className="mt-5 grid gap-5 xl:grid-cols-[1.35fr_1fr]">
            <article id="scan" className="panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Getting started</p>
                  <h2 className="mt-1 text-lg font-semibold">
                    Safe inbox setup
                  </h2>
                </div>
                <span className="text-xs text-muted-foreground">
                  {setupComplete} of 3 complete
                </span>
              </div>
              <div className="mt-5 divide-y">
                {steps.map((step, index) => (
                  <div
                    key={step[0]}
                    className="flex items-center gap-4 py-4 first:pt-0 last:pb-0"
                  >
                    <span
                      className={`step-number ${index < setupComplete ? 'step-ready' : ''}`}
                    >
                      {index + 1}
                    </span>
                    <div className="flex-1">
                      <p className="text-sm font-semibold">{step[0]}</p>
                      <p className="text-xs text-muted-foreground">{step[1]}</p>
                    </div>
                    {index === 0 ? (
                      <Link className="primary-button" href="/setup">
                        {connected ? 'Manage' : 'Configure'}{' '}
                        <ChevronRight size={15} />
                      </Link>
                    ) : index === 1 && connected ? (
                      <Link className="primary-button" href="/full-scan">
                        {scan ? 'View scan' : 'Start scan'}{' '}
                        <ChevronRight size={15} />
                      </Link>
                    ) : index === 2 && scan?.status === 'completed' ? (
                      <Link className="primary-button" href="/full-scan">
                        Review <ChevronRight size={15} />
                      </Link>
                    ) : (
                      <LockKeyhole
                        className="text-muted-foreground"
                        size={16}
                      />
                    )}
                  </div>
                ))}
              </div>
            </article>
            <article
              id="safety"
              className="panel border-safe/20 bg-safe-soft/35"
            >
              <div className="flex items-center gap-3">
                <span className="grid size-10 place-items-center rounded-xl bg-safe text-white">
                  <ShieldCheck size={20} />
                </span>
                <div>
                  <p className="eyebrow text-safe">Protection policy</p>
                  <h2 className="mt-1 text-lg font-semibold">
                    Nothing important gets deleted
                  </h2>
                </div>
              </div>
              <ul className="mt-5 space-y-3 text-sm">
                {[
                  'Delete moves selected messages to Trash',
                  'Attachments and sensitive categories protected',
                  'Low-confidence decisions require review',
                  'Every proposed action is auditable',
                ].map((x) => (
                  <li key={x} className="flex gap-2.5">
                    <CheckCircle2 className="text-safe" size={16} />
                    {x}
                  </li>
                ))}
              </ul>
            </article>
          </div>
          <article id="archive" className="panel mt-5">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">Large message offload</p>
                <h2 className="mt-1 text-lg font-semibold">Archive storage</h2>
                <p className="mt-1 text-sm text-muted-foreground">
                  Export, verify integrity, then present mailbox cleanup for
                  approval.
                </p>
              </div>
              <span className="rounded-full bg-muted px-3 py-1 text-xs">
                {dashboard?.archive
                  ? 'Verified destination'
                  : 'No destination configured'}
              </span>
            </div>
            <div className="mt-5 grid gap-4 md:grid-cols-2">
              <form
                onSubmit={configureArchive}
                className="destination items-start"
              >
                <span className="grid size-10 place-items-center rounded-lg bg-secondary">
                  <HardDrive size={19} />
                </span>
                <span className="min-w-0 flex-1 text-left">
                  <span className="block text-sm font-semibold">
                    Local / NAS
                  </span>
                  <span className="mt-1 block text-xs text-muted-foreground">
                    Absolute folder or UNC network path
                  </span>
                  <Input
                    value={archivePath}
                    onChange={(event) => setArchivePath(event.target.value)}
                    placeholder="D:\\MailArchive or \\\\NAS\\MailArchive"
                    className="mt-3"
                    required
                  />
                  <span className="mt-3 flex items-center gap-3">
                    <Button
                      type="submit"
                      disabled={archivePending || !archivePath}
                    >
                      {archivePending ? 'Verifying…' : 'Verify and save'}
                    </Button>
                    {archiveMessage && (
                      <span className="text-xs font-semibold text-safe">
                        {archiveMessage}
                      </span>
                    )}
                  </span>
                </span>
              </form>
              <Link href="/archive" className="destination items-start">
                <span className="grid size-10 place-items-center rounded-lg bg-secondary">
                  <Box size={19} />
                </span>
                <span className="flex-1 text-left">
                  <span className="block text-sm font-semibold">Dropbox</span>
                  <span className="text-xs text-muted-foreground">
                    OAuth2 PKCE, encrypted refresh token, and verified uploads
                  </span>
                </span>
                <span className="text-xs font-semibold text-muted-foreground">
                  Configure
                </span>
              </Link>
            </div>
          </article>
        </section>
      </div>
    </main>
  );
}
