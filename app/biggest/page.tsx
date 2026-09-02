'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { ArrowLeft, Archive, Download, Loader2, Trash2 } from 'lucide-react';
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
const keyOf = (item: Mail) => `${item.job_id}:${item.folder}:${item.uid}`;
const bytes = (value: number) =>
  value >= 1_048_576
    ? `${(value / 1_048_576).toFixed(1)} MB`
    : `${(value / 1024).toFixed(1)} KB`;

export default function BiggestMailPage() {
  const { accounts, accountId, setAccountId } = useAccountSelection();
  const [items, setItems] = useState<Mail[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState<{ key: string; direction: SortDirection }>({
    key: 'size',
    direction: 'desc',
  });
  const accessors: Record<string, (item: Mail) => string | number> = {
    subject: (item) => item.subject,
    folder: (item) => item.folder,
    size: (item) => item.size_bytes,
  };
  const visible = filterAndSort(
    items,
    query,
    (item) => `${item.subject} ${item.sender} ${item.folder}`,
    accessors[sort.key],
    sort.direction,
  );
  const changeSort = (key: string) =>
    setSort((old) => nextSort(old.key, old.direction, key));

  async function load(id = accountId) {
    if (!id) {
      setItems([]);
      return;
    }
    const response = await fetch(
      `${API_URL}/api/mail/biggest?account_id=${encodeURIComponent(id)}`,
      {
        cache: 'no-store',
      },
    );
    if (!response.ok) throw new Error('Could not load the mailbox inventory');
    setItems(((await response.json()) as { items: Mail[] }).items);
  }
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSelected(new Set());
      void load(accountId).catch((e) => setError(e.message));
    }, 0);
    return () => window.clearTimeout(timer);
  }, [accountId]);

  async function run(action: Action) {
    const chosen = items.filter((item) => selected.has(keyOf(item)));
    if (!chosen.length) return;
    const label =
      action === 'delete'
        ? 'move to Trash'
        : action === 'archive'
          ? 'move to Archive'
          : 'export to NAS and move to Trash';
    setPending(true);
    setError('');
    setMessage('');
    try {
      const requestBody = {
        action,
        confirmed: true,
        items: chosen.map(({ job_id, folder, uid }) => ({
          job_id,
          folder,
          uid,
        })),
      };
      const previewResponse = await fetch(
        `${API_URL}/api/mail/actions/preview`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(requestBody),
        },
      );
      const preview = (await previewResponse.json()) as {
        count?: number;
        bytes?: number;
        protected?: number;
        detail?: string;
      };
      if (!previewResponse.ok)
        throw new Error(preview.detail || 'Preview failed safely');
      if (preview.protected)
        throw new Error(
          `${preview.protected} protected message(s) were blocked by Safety Rules`,
        );
      if (
        !window.confirm(
          `Preview: ${label} for ${preview.count ?? chosen.length} message(s), ${bytes(preview.bytes ?? 0)} total. Continue?`,
        )
      )
        return;
      const response = await fetch(`${API_URL}/api/mail/actions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(requestBody),
      });
      const payload = (await response.json()) as {
        completed?: number;
        failed?: number;
        unavailable?: number;
        exported_move_failed?: number;
        rescan_recommended?: boolean;
        detail?: string;
      };
      if (!response.ok)
        throw new Error(payload.detail || 'Action failed safely');
      const parts = [`${payload.completed ?? 0} message(s) completed`];
      if (payload.unavailable)
        parts.push(
          `${payload.unavailable} no longer at the scanned location — run a new Full mailbox scan`,
        );
      if (payload.exported_move_failed)
        parts.push(
          `${payload.exported_move_failed} exported safely but could not be moved`,
        );
      if (payload.failed) parts.push(`${payload.failed} failed safely`);
      if (!(payload.completed ?? 0) && payload.rescan_recommended)
        setError(parts.join(' · '));
      else setMessage(parts.join(' · '));
      setSelected(new Set());
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Action failed');
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
            <p className="eyebrow">Mailbox storage</p>
            <h1 className="mt-2 text-3xl font-semibold">Biggest mails</h1>
            <p className="mt-2 text-sm text-muted-foreground">
              Largest indexed messages across the latest complete scan.
            </p>
          </div>
          <span className="text-sm font-semibold">
            {selected.size} selected
          </span>
        </div>
        <AccountSwitcher
          accounts={accounts}
          accountId={accountId}
          onChange={setAccountId}
          className="mt-4"
        />
        <div className="panel mt-6">
          <div className="flex flex-wrap gap-2">
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
              {pending ? <Loader2 className="animate-spin" /> : <Download />}
              Export to NAS + Trash
            </Button>
          </div>
          <p className="mt-3 text-xs text-muted-foreground">
            Nothing is permanently expunged. NAS export is verified before the
            mailbox move.
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
            <AlertTitle>Completed</AlertTitle>
            <AlertDescription>{message}</AlertDescription>
          </Alert>
        )}
        <div className="panel mt-4 overflow-x-auto">
          <TableFilterBar
            value={query}
            onChange={setQuery}
            shown={visible.length}
            total={items.length}
            placeholder="Filter by subject, sender, or folder…"
          />
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-10"></TableHead>
                <SortableTableHead
                  label="Subject / sender"
                  sortKey="subject"
                  activeKey={sort.key}
                  direction={sort.direction}
                  onSort={changeSort}
                />
                <SortableTableHead
                  label="Folder"
                  sortKey="folder"
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
              {visible.map((item) => {
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
                      <p className="max-w-xl truncate text-sm font-medium">
                        {item.subject}
                      </p>
                      <p className="max-w-xl truncate text-xs text-muted-foreground">
                        {item.sender}
                      </p>
                    </TableCell>
                    <TableCell className="text-xs">{item.folder}</TableCell>
                    <TableCell className="text-right font-semibold">
                      {bytes(item.size_bytes)}
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
