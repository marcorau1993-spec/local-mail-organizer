'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import {
  Archive,
  ArrowLeft,
  Download,
  Loader2,
  MailCheck,
  Send,
  Trash2,
  Users,
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

const API_URL = 'http://127.0.0.1:8765';
type SenderRow = {
  sender: string;
  sender_domain: string;
  messages: number;
  bytes: number;
  oldest_date?: string;
  newest_date?: string;
};
type Mail = {
  job_id: string;
  folder: string;
  uid: string;
  subject: string;
  sender: string;
  size_bytes: number;
  internal_date?: string;
};
type Action = 'delete' | 'archive' | 'export_delete';
type View = 'senders' | 'sent';
const keyOf = (item: Mail) => `${item.job_id}:${item.folder}:${item.uid}`;
const formatBytes = (value = 0) =>
  value >= 1_073_741_824
    ? `${(value / 1_073_741_824).toFixed(1)} GB`
    : value >= 1_048_576
      ? `${(value / 1_048_576).toFixed(1)} MB`
      : `${(value / 1024).toFixed(1)} KB`;
const senderAccessors: Record<string, (item: SenderRow) => string | number> = {
  sender: (item) => item.sender,
  messages: (item) => item.messages,
  size: (item) => item.bytes,
};
const sentAccessors: Record<string, (item: Mail) => string | number> = {
  subject: (item) => item.subject,
  folder: (item) => item.folder,
  date: (item) => item.internal_date ?? '',
  size: (item) => item.size_bytes,
};

export default function MailActivityPage({
  initialView = 'senders',
  standalone = false,
}: {
  initialView?: View;
  standalone?: boolean;
} = {}) {
  const { accounts, accountId, setAccountId } = useAccountSelection();
  const [senders, setSenders] = useState<SenderRow[]>([]);
  const [sent, setSent] = useState<Mail[]>([]);
  const [sentFolders, setSentFolders] = useState<string[]>([]);
  const [sentTotal, setSentTotal] = useState({ messages: 0, bytes: 0 });
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [selectedSenders, setSelectedSenders] = useState<Set<string>>(
    new Set(),
  );
  const [senderQuery, setSenderQuery] = useState('');
  const [sentQuery, setSentQuery] = useState('');
  const [senderSort, setSenderSort] = useState<{
    key: string;
    direction: SortDirection;
  }>({ key: 'messages', direction: 'desc' });
  const [sentSort, setSentSort] = useState<{
    key: string;
    direction: SortDirection;
  }>({ key: 'size', direction: 'desc' });
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [view] = useState<View>(initialView);

  async function load(id = accountId) {
    if (!id) return;
    const response = await fetch(
      `${API_URL}/api/mail/activity-overview?account_id=${encodeURIComponent(id)}`,
      { cache: 'no-store' },
    );
    if (!response.ok)
      throw new Error('Could not load sender and sent-mail overview');
    const payload = (await response.json()) as {
      senders: SenderRow[];
      sent: Mail[];
      sent_summary: { folders: string[]; messages: number; bytes: number };
    };
    setSenders(payload.senders);
    setSent(payload.sent);
    setSentFolders(payload.sent_summary.folders);
    setSentTotal(payload.sent_summary);
  }
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSelected(new Set());
      setSelectedSenders(new Set());
      void load(accountId).catch((reason) =>
        setError(
          reason instanceof Error ? reason.message : 'Could not load overview',
        ),
      );
    }, 0);
    return () => window.clearTimeout(timer);
  }, [accountId]);
  useEffect(() => {
    if (!standalone) window.location.replace('/senders');
  }, [standalone]);

  const visibleSenders = useMemo(
    () =>
      filterAndSort(
        senders,
        senderQuery,
        (item) => `${item.sender} ${item.sender_domain}`,
        senderAccessors[senderSort.key],
        senderSort.direction,
      ),
    [senders, senderQuery, senderSort],
  );
  const visibleSent = useMemo(
    () =>
      filterAndSort(
        sent,
        sentQuery,
        (item) => `${item.subject} ${item.sender} ${item.folder}`,
        sentAccessors[sentSort.key],
        sentSort.direction,
      ),
    [sent, sentQuery, sentSort],
  );
  const selectedItems = sent.filter((item) => selected.has(keyOf(item)));
  const selectedSenderRows = senders.filter((item) =>
    selectedSenders.has(item.sender),
  );
  const selectedSenderMessages = selectedSenderRows.reduce(
    (total, item) => total + item.messages,
    0,
  );
  const selectedSenderBytes = selectedSenderRows.reduce(
    (total, item) => total + item.bytes,
    0,
  );
  const selectedBytes = selectedItems.reduce(
    (total, item) => total + item.size_bytes,
    0,
  );

  async function run(action: Action) {
    if (!selectedItems.length) return;
    const verb =
      action === 'delete'
        ? 'move to Trash'
        : action === 'archive'
          ? 'archive'
          : 'export to NAS and move to Trash';
    const body = {
      action,
      confirmed: true,
      items: selectedItems.map(({ job_id, folder, uid }) => ({
        job_id,
        folder,
        uid,
      })),
    };
    setPending(true);
    setError('');
    setMessage('');
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
        protected?: number;
        detail?: string;
      };
      if (!previewResponse.ok)
        throw new Error(
          typeof preview.detail === 'string'
            ? preview.detail
            : 'Preview stopped safely',
        );
      if (
        !window.confirm(
          `Preview: ${verb} ${preview.count ?? selectedItems.length} sent message(s), ${formatBytes(preview.bytes ?? selectedBytes)} total?`,
        )
      )
        return;
      const response = await fetch(`${API_URL}/api/mail/actions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const payload = (await response.json()) as {
        completed?: number;
        failed?: number;
        unavailable?: number;
        detail?: string;
      };
      if (!response.ok)
        throw new Error(payload.detail || 'Action stopped safely');
      setMessage(
        `${payload.completed ?? 0} completed · ${payload.failed ?? 0} failed · ${payload.unavailable ?? 0} no longer at the scanned location`,
      );
      setSelected(new Set());
      await load();
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : 'Action stopped safely',
      );
    } finally {
      setPending(false);
    }
  }

  async function cleanupSenders(rows = selectedSenderRows) {
    if (!accountId || !rows.length) return;
    if (rows.length > 10) {
      setError('Select at most 10 sender addresses per cleanup run.');
      return;
    }
    setPending(true);
    setError('');
    setMessage('');
    try {
      const base = {
        account_id: accountId,
        senders: rows.map((item) => item.sender),
      };
      const previewResponse = await fetch(
        `${API_URL}/api/mail/senders/cleanup-preview`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...base, confirmed: false }),
        },
      );
      const preview = (await previewResponse.json()) as {
        messages?: number;
        actionable?: number;
        protected?: number;
        bytes?: number;
        detail?: string;
      };
      if (!previewResponse.ok)
        throw new Error(
          preview.detail || 'Sender cleanup preview stopped safely',
        );
      if (
        !window.confirm(
          `Move all ${preview.actionable ?? 0} actionable mail(s) from ${rows.length} selected sender(s) to Trash? ${preview.protected ?? 0} protected mail(s) will stay in place. Total actionable size: ${formatBytes(preview.bytes ?? 0)}.`,
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
      setMessage(
        `${result.completed ?? 0} moved to Trash · ${result.protected ?? 0} protected · ${result.failed ?? 0} failed · ${result.unavailable ?? 0} unavailable`,
      );
      setSelectedSenders(new Set());
      await load();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : 'Sender cleanup stopped safely',
      );
    } finally {
      setPending(false);
    }
  }

  if (!standalone) {
    return (
      <main className="min-h-screen bg-background p-8 text-foreground">
        <p className="text-sm text-muted-foreground">Opening Top senders…</p>
      </main>
    );
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
            <p className="eyebrow">Mailbox traffic & storage</p>
            <h1 className="mt-2 text-3xl font-semibold">
              {view === 'senders' ? 'Sender overview' : 'Sent mail'}
            </h1>
            <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
              {view === 'senders'
                ? 'See which exact sender identities created the most mail and clean up complete sender histories.'
                : 'Find and manage large messages in every detected Sent folder.'}
            </p>
            <AccountSwitcher
              accounts={accounts}
              accountId={accountId}
              onChange={setAccountId}
              className="mt-4"
            />
          </div>
          <div className="rounded-xl border bg-card px-4 py-3 text-sm">
            {view === 'senders' ? (
              <>
                <b>{senders.length.toLocaleString()}</b> sender identities
              </>
            ) : (
              <>
                <b>{sentTotal.messages.toLocaleString()}</b> sent messages ·{' '}
                <b>{formatBytes(sentTotal.bytes)}</b>
              </>
            )}
          </div>
        </div>
        {error && (
          <Alert variant="destructive" className="mt-5">
            <AlertTitle>Stopped safely</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {message && (
          <Alert className="mt-5">
            <AlertTitle>Completed</AlertTitle>
            <AlertDescription>{message}</AlertDescription>
          </Alert>
        )}

        {view === 'senders' && (
          <section className="panel mt-6">
            <div className="mb-4 flex items-center gap-2">
              <Users size={19} />
              <div>
                <h2 className="font-semibold">Top sender addresses</h2>
                <p className="text-xs text-muted-foreground">
                  Ranked by messages; switch to size to find storage-heavy
                  senders.
                </p>
              </div>
            </div>
            <TableFilterBar
              value={senderQuery}
              onChange={setSenderQuery}
              shown={visibleSenders.length}
              total={senders.length}
              placeholder="Filter sender address or domain…"
            />
            <div className="mb-4 flex flex-wrap items-center gap-2 rounded-xl border bg-muted/20 p-3">
              <Button
                variant="destructive"
                disabled={!selectedSenders.size || pending}
                onClick={() => void cleanupSenders()}
              >
                {pending ? <Loader2 className="animate-spin" /> : <Trash2 />}
                Move all mails from selected senders to Trash
              </Button>
              <Button
                variant="outline"
                disabled={!visibleSenders.length || pending}
                onClick={() =>
                  setSelectedSenders(
                    new Set(
                      visibleSenders.slice(0, 10).map((item) => item.sender),
                    ),
                  )
                }
              >
                Select visible (max 10)
              </Button>
              <Button
                variant="ghost"
                disabled={!selectedSenders.size || pending}
                onClick={() => setSelectedSenders(new Set())}
              >
                Clear
              </Button>
              <span className="ml-auto text-sm font-semibold">
                {selectedSenders.size} senders ·{' '}
                {selectedSenderMessages.toLocaleString()} mails ·{' '}
                {formatBytes(selectedSenderBytes)}
              </span>
            </div>
            <Table className="table-fixed">
              <colgroup>
                <col className="w-12" />
                <col />
                <col className="w-32" />
                <col className="w-32" />
                <col className="w-36" />
              </colgroup>
              <TableHeader>
                <TableRow>
                  <TableHead aria-label="Select sender" />
                  <SortableTableHead
                    label="Sender"
                    sortKey="sender"
                    activeKey={senderSort.key}
                    direction={senderSort.direction}
                    onSort={(key) =>
                      setSenderSort((old) =>
                        nextSort(old.key, old.direction, key),
                      )
                    }
                  />
                  <SortableTableHead
                    label="Messages"
                    sortKey="messages"
                    activeKey={senderSort.key}
                    direction={senderSort.direction}
                    onSort={(key) =>
                      setSenderSort((old) =>
                        nextSort(old.key, old.direction, key),
                      )
                    }
                    className="w-32 text-right"
                  />
                  <SortableTableHead
                    label="Storage"
                    sortKey="size"
                    activeKey={senderSort.key}
                    direction={senderSort.direction}
                    onSort={(key) =>
                      setSenderSort((old) =>
                        nextSort(old.key, old.direction, key),
                      )
                    }
                    className="w-32 text-right"
                  />
                  <TableHead className="w-36 text-right">Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {visibleSenders.map((item, index) => (
                  <TableRow key={`${item.sender}:${index}`}>
                    <TableCell>
                      <Checkbox
                        checked={selectedSenders.has(item.sender)}
                        onCheckedChange={(checked) =>
                          setSelectedSenders((old) => {
                            const next = new Set(old);
                            if (checked && next.size < 10)
                              next.add(item.sender);
                            else if (!checked) next.delete(item.sender);
                            return next;
                          })
                        }
                        aria-label={`Select ${item.sender}`}
                      />
                    </TableCell>
                    <TableCell>
                      <p className="font-medium">{item.sender}</p>
                      <p className="text-xs text-muted-foreground">
                        {item.sender_domain || 'Unknown domain'}
                      </p>
                    </TableCell>
                    <TableCell className="text-right font-semibold">
                      {item.messages.toLocaleString()}
                    </TableCell>
                    <TableCell className="text-right">
                      {formatBytes(item.bytes)}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={pending}
                        onClick={() => void cleanupSenders([item])}
                      >
                        <Trash2 size={14} /> All to Trash
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </section>
        )}

        {view === 'sent' && (
          <>
            <section className="panel mt-6">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <Send size={19} />
                  <div>
                    <h2 className="font-semibold">Sent mailbox storage</h2>
                    <p className="text-xs text-muted-foreground">
                      Detected folders:{' '}
                      {sentFolders.join(', ') || 'none in the latest scan'}
                    </p>
                  </div>
                </div>
                <span className="text-sm font-semibold">
                  {selected.size} selected · {formatBytes(selectedBytes)}
                </span>
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                <Button
                  variant="destructive"
                  disabled={!selected.size || pending}
                  onClick={() => void run('delete')}
                >
                  <Trash2 />
                  Move to Trash
                </Button>
                <Button
                  variant="outline"
                  disabled={!selected.size || pending}
                  onClick={() => void run('archive')}
                >
                  <Archive />
                  Archive
                </Button>
                <Button
                  disabled={!selected.size || pending}
                  onClick={() => void run('export_delete')}
                >
                  {pending ? (
                    <Loader2 className="animate-spin" />
                  ) : (
                    <Download />
                  )}
                  Export to NAS + Trash
                </Button>
                <Button
                  variant="outline"
                  disabled={!visibleSent.length || pending}
                  onClick={() =>
                    setSelected(new Set(visibleSent.slice(0, 100).map(keyOf)))
                  }
                >
                  <MailCheck />
                  Select visible (max 100)
                </Button>
                <Button
                  variant="ghost"
                  disabled={!selected.size || pending}
                  onClick={() => setSelected(new Set())}
                >
                  Clear
                </Button>
              </div>
              <p className="mt-3 text-xs text-muted-foreground">
                Nothing is permanently deleted here. NAS exports are verified
                before the mailbox move.
              </p>
            </section>
            <section className="panel mt-4 overflow-x-auto">
              <TableFilterBar
                value={sentQuery}
                onChange={setSentQuery}
                shown={visibleSent.length}
                total={sent.length}
                placeholder="Filter sent subject, sender, or folder…"
              />
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-10" />
                    <SortableTableHead
                      label="Subject"
                      sortKey="subject"
                      activeKey={sentSort.key}
                      direction={sentSort.direction}
                      onSort={(key) =>
                        setSentSort((old) =>
                          nextSort(old.key, old.direction, key),
                        )
                      }
                    />
                    <SortableTableHead
                      label="Folder"
                      sortKey="folder"
                      activeKey={sentSort.key}
                      direction={sentSort.direction}
                      onSort={(key) =>
                        setSentSort((old) =>
                          nextSort(old.key, old.direction, key),
                        )
                      }
                      className="w-40"
                    />
                    <SortableTableHead
                      label="Date"
                      sortKey="date"
                      activeKey={sentSort.key}
                      direction={sentSort.direction}
                      onSort={(key) =>
                        setSentSort((old) =>
                          nextSort(old.key, old.direction, key),
                        )
                      }
                      className="w-48"
                    />
                    <SortableTableHead
                      label="Size"
                      sortKey="size"
                      activeKey={sentSort.key}
                      direction={sentSort.direction}
                      onSort={(key) =>
                        setSentSort((old) =>
                          nextSort(old.key, old.direction, key),
                        )
                      }
                      className="w-28 text-right"
                    />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {visibleSent.map((item) => {
                    const key = keyOf(item);
                    return (
                      <TableRow key={key}>
                        <TableCell>
                          <Checkbox
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
                        <TableCell>
                          <p className="max-w-2xl truncate font-medium">
                            {item.subject || '(no subject)'}
                          </p>
                          <p className="text-xs text-muted-foreground">
                            {item.sender}
                          </p>
                        </TableCell>
                        <TableCell>{item.folder}</TableCell>
                        <TableCell className="text-xs">
                          {item.internal_date || 'Unknown'}
                        </TableCell>
                        <TableCell className="text-right font-semibold">
                          {formatBytes(item.size_bytes)}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
              {!visibleSent.length && (
                <p className="py-10 text-center text-sm text-muted-foreground">
                  No Sent folder messages were found in the latest complete
                  scan.
                </p>
              )}
            </section>
          </>
        )}
      </div>
    </main>
  );
}
