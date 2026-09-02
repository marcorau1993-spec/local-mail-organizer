'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import {
  ArrowLeft,
  Bot,
  CheckCircle2,
  Loader2,
  ShieldAlert,
  Trash2,
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
type Finding = {
  job_id: string;
  folder: string;
  uid: string;
  subject: string;
  sender: string;
  actual_sender: string;
  actual_domain: string;
  size_bytes: number;
  risk_score: number;
  risk: string;
  reasons: string[];
};
type Assessment = {
  finding_id: string;
  verdict: string;
  confidence: number;
  reason: string;
};
type Authentication = {
  spf: string | null;
  dkim: string | null;
  dmarc: string | null;
  reply_to: string | null;
  return_path: string | null;
};
const keyOf = (item: Finding) => `${item.job_id}:${item.folder}:${item.uid}`;

export default function SecurityPage() {
  const { accounts, accountId, setAccountId } = useAccountSelection();
  const [items, setItems] = useState<Finding[]>([]);
  const [analyzed, setAnalyzed] = useState(0);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [assessments, setAssessments] = useState<Record<string, Assessment>>(
    {},
  );
  const [authentication, setAuthentication] = useState<
    Record<string, Authentication>
  >({});
  const [query, setQuery] = useState('');
  const [risk, setRisk] = useState<'all' | 'high' | 'medium'>('all');
  const [sort, setSort] = useState<{ key: string; direction: SortDirection }>({
    key: 'risk',
    direction: 'desc',
  });
  const load = useCallback(async () => {
    if (!accountId) {
      setItems([]);
      setAnalyzed(0);
      return;
    }
    const response = await fetch(
      `${API_URL}/api/security/findings?account_id=${encodeURIComponent(accountId)}`,
      {
        cache: 'no-store',
      },
    );
    if (!response.ok) throw new Error('Could not analyze the latest inventory');
    const payload = (await response.json()) as {
      findings: Finding[];
      analyzed: number;
      assessments?: Assessment[];
    };
    setItems(payload.findings);
    setAnalyzed(payload.analyzed);
    setAssessments(
      Object.fromEntries(
        (payload.assessments ?? []).map((item) => [item.finding_id, item]),
      ),
    );
  }, [accountId]);
  useEffect(() => {
    const timer = window.setTimeout(
      () =>
        void load().catch((reason) =>
          setError(
            reason instanceof Error
              ? reason.message
              : 'Security analysis failed',
          ),
        ),
      0,
    );
    return () => window.clearTimeout(timer);
  }, [load]);
  const filtered = useMemo(
    () => items.filter((item) => risk === 'all' || item.risk === risk),
    [items, risk],
  );
  const visible = filterAndSort(
    filtered,
    query,
    (item) =>
      `${item.subject} ${item.sender} ${item.actual_domain} ${item.folder} ${item.reasons.join(' ')}`,
    (item) =>
      sort.key === 'message'
        ? item.subject
        : sort.key === 'sender'
          ? item.actual_domain
          : sort.key === 'folder'
            ? item.folder
            : item.risk_score,
    sort.direction,
  );
  const changeSort = (key: string) =>
    setSort((old) => nextSort(old.key, old.direction, key));
  async function moveToTrash() {
    const chosen = items.filter((item) => selected.has(keyOf(item)));
    if (!chosen.length) return;
    if (
      !window.confirm(
        `Move ${chosen.length} suspected phishing message(s) to Trash? Nothing is permanently deleted.`,
      )
    )
      return;
    setPending(true);
    setError('');
    setMessage('');
    try {
      const response = await fetch(`${API_URL}/api/mail/actions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action: 'delete',
          confirmed: true,
          items: chosen.map(({ job_id, folder, uid }) => ({
            job_id,
            folder,
            uid,
          })),
        }),
      });
      const payload = (await response.json()) as {
        completed?: number;
        detail?: string;
      };
      if (!response.ok)
        throw new Error(payload.detail || 'Security action stopped safely');
      setMessage(`${payload.completed ?? 0} message(s) moved to Trash`);
      setSelected(new Set());
      await load();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : 'Security action stopped safely',
      );
    } finally {
      setPending(false);
    }
  }
  async function markSafe() {
    const chosen = items.filter((item) => selected.has(keyOf(item)));
    if (!chosen.length) return;
    if (
      !window.confirm(`Mark ${chosen.length} exact sender address(es) as safe?`)
    )
      return;
    setPending(true);
    setError('');
    setMessage('');
    try {
      const response = await fetch(`${API_URL}/api/security/safe`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          confirmed: true,
          items: chosen.map(({ job_id, folder, uid }) => ({
            job_id,
            folder,
            uid,
          })),
        }),
      });
      const payload = (await response.json()) as {
        saved?: number;
        detail?: string;
      };
      if (!response.ok)
        throw new Error(payload.detail || 'Could not save security feedback');
      setMessage(`${payload.saved ?? 0} sender address(es) marked as safe`);
      setSelected(new Set());
      await load();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : 'Could not save security feedback',
      );
    } finally {
      setPending(false);
    }
  }
  async function askQwen() {
    const chosen = items.filter((item) => selected.has(keyOf(item)));
    if (!chosen.length) return;
    setPending(true);
    setError('');
    try {
      let completed = 0;
      for (let start = 0; start < chosen.length; start += 25) {
        const batch = chosen.slice(start, start + 25);
        const response = await fetch(`${API_URL}/api/security/qwen-review`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            items: batch.map(({ job_id, folder, uid }) => ({
              job_id,
              folder,
              uid,
            })),
          }),
        });
        const payload = (await response.json()) as {
          assessments?: Assessment[];
          authentication?: Record<string, Authentication>;
          detail?: string;
        };
        if (!response.ok)
          throw new Error(
            payload.detail || `Qwen review stopped after ${completed} messages`,
          );
        completed += payload.assessments?.length ?? 0;
        setAssessments((old) => ({
          ...old,
          ...Object.fromEntries(
            (payload.assessments ?? []).map((item) => [item.finding_id, item]),
          ),
        }));
        setAuthentication((old) => ({ ...old, ...payload.authentication }));
        setMessage(
          `Qwen reviewed ${completed} of ${chosen.length} selected messages…`,
        );
      }
      setMessage(`${completed} persistent Qwen second opinions completed`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Qwen review failed');
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
            <p className="eyebrow">Mailbox security</p>
            <h1 className="mt-2 text-3xl font-semibold">
              Spam & phishing finder
            </h1>
            <AccountSwitcher
              accounts={accounts}
              accountId={accountId}
              onChange={setAccountId}
              className="mt-4"
            />
            <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
              Explainable local checks identify possible brand impersonation and
              contextual inconsistencies. A finding is not proof of phishing and
              always requires review.
            </p>
          </div>
          <Badge variant="destructive">
            <ShieldAlert />
            Review required
          </Badge>
        </div>
        <section className="panel mt-6">
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="destructive"
              disabled={!selected.size || pending}
              onClick={() => void moveToTrash()}
            >
              {pending ? <Loader2 className="animate-spin" /> : <Trash2 />}Move
              selected to Trash
            </Button>
            <Button
              variant="outline"
              disabled={!selected.size || pending}
              onClick={() => void markSafe()}
            >
              <CheckCircle2 />
              Mark selected as safe
            </Button>
            <Button
              variant="outline"
              disabled={!selected.size || pending}
              onClick={() => void askQwen()}
            >
              <Bot />
              Ask Qwen (batches of 25)
            </Button>
            <Button
              variant="outline"
              disabled={!visible.length || pending}
              onClick={() =>
                setSelected(new Set(visible.slice(0, 100).map(keyOf)))
              }
            >
              Select visible (max 100)
            </Button>
            <Button
              variant="ghost"
              disabled={!selected.size || pending}
              onClick={() => setSelected(new Set())}
            >
              Clear
            </Button>
            {(['all', 'high', 'medium'] as const).map((value) => (
              <Button
                key={value}
                variant={risk === value ? 'secondary' : 'outline'}
                onClick={() => {
                  setRisk(value);
                  setSelected(new Set());
                }}
              >
                {value} risk
              </Button>
            ))}
          </div>
          <p className="mt-3 text-xs text-muted-foreground">
            {analyzed.toLocaleString()} indexed messages checked ·{' '}
            {items.length.toLocaleString()} require review · no message is
            deleted automatically.
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
            <AlertTitle>Completed</AlertTitle>
            <AlertDescription>{message}</AlertDescription>
          </Alert>
        )}
        <section className="panel mt-4 overflow-hidden">
          <TableFilterBar
            value={query}
            onChange={setQuery}
            shown={visible.length}
            total={filtered.length}
            placeholder="Filter subject, sender, domain, folder, or reason…"
          />
          <Table className="w-full table-fixed">
            <TableHeader>
              <TableRow>
                <TableHead className="w-10" />
                <SortableTableHead
                  label="Message"
                  sortKey="message"
                  activeKey={sort.key}
                  direction={sort.direction}
                  onSort={changeSort}
                />
                <SortableTableHead
                  label="Actual sender"
                  sortKey="sender"
                  activeKey={sort.key}
                  direction={sort.direction}
                  onSort={changeSort}
                  className="w-[18%]"
                />
                <SortableTableHead
                  label="Folder"
                  sortKey="folder"
                  activeKey={sort.key}
                  direction={sort.direction}
                  onSort={changeSort}
                  className="w-[12%]"
                />
                <SortableTableHead
                  label="Risk"
                  sortKey="risk"
                  activeKey={sort.key}
                  direction={sort.direction}
                  onSort={changeSort}
                  className="w-[10%] text-right"
                />
                <TableHead className="w-[22%]">Qwen second opinion</TableHead>
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
                        disabled={pending}
                        onCheckedChange={(checked) =>
                          setSelected((old) => {
                            const next = new Set(old);
                            if (checked && next.size < 100) next.add(key);
                            else if (!checked) next.delete(key);
                            return next;
                          })
                        }
                      />
                    </TableCell>
                    <TableCell className="whitespace-normal break-words align-top">
                      <p className="line-clamp-2 font-semibold">
                        {item.subject}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        Shown as: {item.sender}
                      </p>
                      <ul className="mt-2 list-disc pl-4 text-xs text-destructive">
                        {item.reasons.map((reason) => (
                          <li key={reason}>{reason}</li>
                        ))}
                      </ul>
                    </TableCell>
                    <TableCell className="whitespace-normal break-all align-top">
                      <p className="line-clamp-2 font-medium">
                        {item.actual_sender}
                      </p>
                      <p className="break-all text-xs text-muted-foreground">
                        {item.actual_domain}
                      </p>
                    </TableCell>
                    <TableCell className="break-words align-top">
                      {item.folder}
                    </TableCell>
                    <TableCell className="align-top text-right">
                      <Badge
                        variant={
                          item.risk === 'high' ? 'destructive' : 'secondary'
                        }
                      >
                        {item.risk_score}/100
                      </Badge>
                    </TableCell>
                    <TableCell className="whitespace-normal break-words align-top">
                      {authentication[key] && (
                        <p className="mb-2 text-xs text-muted-foreground">
                          SPF {authentication[key].spf ?? 'unknown'} · DKIM{' '}
                          {authentication[key].dkim ?? 'unknown'} · DMARC{' '}
                          {authentication[key].dmarc ?? 'unknown'}
                        </p>
                      )}
                      {assessments[key] ? (
                        <>
                          <Badge
                            variant={
                              assessments[key].verdict === 'likely_suspicious'
                                ? 'destructive'
                                : 'secondary'
                            }
                          >
                            {assessments[key].verdict.replaceAll('_', ' ')} ·{' '}
                            {Math.round(assessments[key].confidence * 100)}%
                          </Badge>
                          <p className="mt-1 text-xs text-muted-foreground">
                            {assessments[key].reason}
                          </p>
                        </>
                      ) : (
                        <span className="text-xs text-muted-foreground">
                          Not reviewed
                        </span>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
          {!visible.length && (
            <p className="py-10 text-center text-sm text-muted-foreground">
              No matching security findings in the latest complete scan.
            </p>
          )}
        </section>
      </div>
    </main>
  );
}
