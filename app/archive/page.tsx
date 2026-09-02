'use client';

import { useEffect, useState } from 'react';
import type { SyntheticEvent } from 'react';
import Link from 'next/link';
import {
  ArrowLeft,
  CheckCircle2,
  Cloud,
  Download,
  HardDrive,
  ShieldCheck,
  Trash2,
} from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  AccountSwitcher,
  useAccountSelection,
} from '@/components/account-switcher';

const API_URL = 'http://127.0.0.1:8765';

type ArchiveDestination = {
  kind: 'local_nas' | 'dropbox';
  root_path: string;
  verified_at: string;
};

export default function ArchiveStoragePage() {
  const { accounts, accountId, setAccountId, loading } = useAccountSelection();
  const [destination, setDestination] = useState<ArchiveDestination | null>(
    null,
  );
  const [path, setPath] = useState('');
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [dropboxConnected, setDropboxConnected] = useState(false);
  const [dropboxAppKey, setDropboxAppKey] = useState('');
  const [dropboxPath, setDropboxPath] = useState('/MailOrganizer');

  useEffect(() => {
    if (!accountId) return;
    const controller = new AbortController();
    void (async () => {
      setError('');
      setMessage('');
      try {
        const response = await fetch(
          `${API_URL}/api/archive/destination?account_id=${encodeURIComponent(accountId)}`,
          { cache: 'no-store', signal: controller.signal },
        );
        const payload = (await response.json()) as {
          configured: boolean;
          destination: ArchiveDestination | null;
          detail?: string;
        };
        if (!response.ok)
          throw new Error(payload.detail || 'Could not load archive storage');
        setDestination(payload.destination);
        setPath(payload.destination?.root_path ?? '');
        if (payload.destination?.kind === 'dropbox')
          setDropboxPath(payload.destination.root_path);
        const statusResponse = await fetch(
          `${API_URL}/api/archive/dropbox/status?account_id=${encodeURIComponent(accountId)}`,
          { cache: 'no-store', signal: controller.signal },
        );
        if (statusResponse.ok) {
          const status = (await statusResponse.json()) as { connected: boolean };
          setDropboxConnected(status.connected);
        }
      } catch (reason) {
        if (reason instanceof DOMException && reason.name === 'AbortError')
          return;
        setError(
          reason instanceof Error
            ? reason.message
            : 'Could not load archive storage',
        );
      }
    })();
    return () => controller.abort();
  }, [accountId]);

  async function saveDestination(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!accountId) return;
    setPending(true);
    setError('');
    setMessage('');
    try {
      const response = await fetch(`${API_URL}/api/archive/destination`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          account_id: accountId,
          kind: 'local_nas',
          root_path: path.trim(),
        }),
      });
      const payload = (await response.json()) as {
        destination?: ArchiveDestination;
        detail?: string;
      };
      if (!response.ok)
        throw new Error(payload.detail || 'Archive verification failed');
      if (payload.destination) setDestination(payload.destination);
      setMessage('Storage verified and saved for this mailbox.');
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : 'Archive setup failed',
      );
    } finally {
      setPending(false);
    }
  }

  async function connectDropbox() {
    if (!accountId) return;
    setPending(true);
    setError('');
    try {
      const response = await fetch(`${API_URL}/api/archive/dropbox/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ account_id: accountId, app_key: dropboxAppKey.trim() }),
      });
      const payload = (await response.json()) as { authorization_url?: string; detail?: string };
      if (!response.ok || !payload.authorization_url)
        throw new Error(payload.detail || 'Could not start Dropbox authorization');
      window.location.href = payload.authorization_url;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Dropbox connection failed');
      setPending(false);
    }
  }

  async function saveDropbox() {
    if (!accountId) return;
    setPending(true);
    setError('');
    setMessage('');
    try {
      const response = await fetch(`${API_URL}/api/archive/destination`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ account_id: accountId, kind: 'dropbox', root_path: dropboxPath }),
      });
      const payload = (await response.json()) as { destination?: ArchiveDestination; detail?: string };
      if (!response.ok) throw new Error(payload.detail || 'Dropbox verification failed');
      if (payload.destination) setDestination(payload.destination);
      setMessage('Dropbox upload and download verification passed.');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Dropbox setup failed');
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="min-h-screen bg-background px-5 py-8 text-foreground lg:px-8">
      <div className="mx-auto max-w-6xl">
        <Link
          href="/"
          className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft size={16} /> Overview
        </Link>

        <div className="mt-8 flex flex-col justify-between gap-5 sm:flex-row sm:items-end">
          <div>
            <p className="eyebrow">Large message offload</p>
            <h1 className="mt-2 text-3xl font-semibold tracking-[-0.035em]">
              Archive storage
            </h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
              Store complete messages on a local drive or NAS, verify their
              integrity, and only then move the mailbox copy to Trash.
            </p>
          </div>
          <AccountSwitcher
            accounts={accounts}
            accountId={accountId}
            onChange={setAccountId}
          />
        </div>

        {error && (
          <Alert variant="destructive" className="mt-6">
            <AlertTitle>Storage setup stopped safely</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {message && (
          <Alert className="mt-6 border-safe/30 bg-safe-soft/40">
            <CheckCircle2 className="text-safe" />
            <AlertTitle>Archive storage ready</AlertTitle>
            <AlertDescription>{message}</AlertDescription>
          </Alert>
        )}

        <section className="panel mt-6">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Destination</p>
              <h2 className="mt-1 text-lg font-semibold">Local drive or NAS</h2>
            </div>
            <span className="rounded-full bg-muted px-3 py-1 text-xs font-semibold">
              {destination ? 'Verified' : 'Not configured'}
            </span>
          </div>

          <form onSubmit={saveDestination} className="mt-6 grid gap-4">
            <label
              className="grid gap-2 text-sm font-semibold"
              htmlFor="archive-path"
            >
              Absolute folder or UNC network path
              <Input
                id="archive-path"
                value={path}
                onChange={(event) => setPath(event.target.value)}
                placeholder="D:\\MailArchive or \\\\NAS\\MailArchive"
                disabled={!accountId || pending}
                required
              />
            </label>
            <p className="text-xs leading-5 text-muted-foreground">
              The folder is tested for write access before it is saved. The
              setting applies only to the mailbox selected above.
            </p>
            <div className="flex flex-wrap items-center gap-3">
              <Button
                type="submit"
                disabled={!accountId || !path.trim() || pending}
              >
                <HardDrive /> {pending ? 'Verifying…' : 'Verify and save'}
              </Button>
              <Link className="primary-button" href="/biggest">
                <Download size={16} /> Open biggest mails
              </Link>
            </div>
          </form>
        </section>

        <section className="panel mt-6">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Cloud destination</p>
              <h2 className="mt-1 text-lg font-semibold">Dropbox</h2>
              <p className="mt-2 text-xs leading-5 text-muted-foreground">
                Uses Dropbox OAuth with PKCE and an offline refresh token. The token is stored only in Windows Credential Manager.
              </p>
            </div>
            <span className="rounded-full bg-muted px-3 py-1 text-xs font-semibold">
              {dropboxConnected ? 'Connected' : 'Not connected'}
            </span>
          </div>
          {!dropboxConnected ? (
            <div className="mt-6 grid gap-3">
              <label className="grid gap-2 text-sm font-semibold" htmlFor="dropbox-app-key">
                Dropbox app key
                <Input id="dropbox-app-key" value={dropboxAppKey} onChange={(event) => setDropboxAppKey(event.target.value)} placeholder="From the Dropbox App Console" />
              </label>
              <p className="text-xs leading-5 text-muted-foreground">
                Create a scoped Dropbox app with <code>files.content.write</code> and <code>files.content.read</code>, then register <code>http://127.0.0.1:8765/api/archive/dropbox/callback</code> as its redirect URI.
              </p>
              <Button type="button" onClick={() => void connectDropbox()} disabled={!accountId || dropboxAppKey.trim().length < 8 || pending}>
                <Cloud /> Connect Dropbox securely
              </Button>
            </div>
          ) : (
            <div className="mt-6 grid gap-3">
              <label className="grid gap-2 text-sm font-semibold" htmlFor="dropbox-path">
                Dropbox archive folder
                <Input id="dropbox-path" value={dropboxPath} onChange={(event) => setDropboxPath(event.target.value)} placeholder="/MailOrganizer" />
              </label>
              <Button type="button" onClick={() => void saveDropbox()} disabled={!dropboxPath.trim() || pending}>
                <Cloud /> {pending ? 'Verifying…' : 'Verify and use Dropbox'}
              </Button>
            </div>
          )}
        </section>

        <section className="mt-6 grid gap-4 md:grid-cols-3">
          {[
            [
              Download,
              '1. Export',
              'The complete RFC 822 message is written to storage.',
            ],
            [
              ShieldCheck,
              '2. Verify',
              'A checksum verifies the exported file before cleanup.',
            ],
            [
              Trash2,
              '3. Move to Trash',
              'Only the verified mailbox copy is moved; nothing is expunged.',
            ],
          ].map(([Icon, title, description]) => (
            <article className="panel" key={String(title)}>
              <Icon className="text-primary" size={20} />
              <h2 className="mt-4 text-sm font-semibold">{String(title)}</h2>
              <p className="mt-2 text-xs leading-5 text-muted-foreground">
                {String(description)}
              </p>
            </article>
          ))}
        </section>

        {!loading && !accounts.length && (
          <Alert className="mt-6">
            <AlertTitle>No mailbox connected</AlertTitle>
            <AlertDescription>
              Connect a mailbox before configuring its archive destination.
            </AlertDescription>
          </Alert>
        )}
      </div>
    </main>
  );
}
