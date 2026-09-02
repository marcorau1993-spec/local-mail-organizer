'use client';

import { useEffect, useState } from 'react';
import type { SyntheticEvent } from 'react';
import Link from 'next/link';
import {
  ArrowLeft,
  CheckCircle2,
  Eye,
  EyeOff,
  ExternalLink,
  KeyRound,
  Loader2,
  LockKeyhole,
  Server,
  ShieldCheck,
} from 'lucide-react';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

const API_URL = 'http://127.0.0.1:8765';
type Result = {
  connected: boolean;
  folder_count: number;
  credential_saved: boolean;
};
type Provider = {
  key: string;
  display_name: string;
  auth_mode: string;
  connectable: boolean;
  credential_label: string;
  instructions: string[];
  help_url: string;
  imap_host: string;
  imap_port: number;
};

export default function SetupPage() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [providerKey, setProviderKey] = useState('webde');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [visible, setVisible] = useState(false);
  const [saving, setSaving] = useState(true);
  const [pending, setPending] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState('');
  const [microsoftClientId, setMicrosoftClientId] = useState('');
  const [microsoftTenant, setMicrosoftTenant] = useState('common');
  const [oauthCode, setOauthCode] = useState('');
  const [oauthUrl, setOauthUrl] = useState('');
  const provider = providers.find((item) => item.key === providerKey);
  useEffect(() => {
    async function loadProviders() {
      try {
        const response = await fetch(`${API_URL}/api/providers`, {
          cache: 'no-store',
        });
        const payload = (await response.json()) as { providers: Provider[] };
        setProviders(payload.providers);
      } catch {
        setError('Could not load provider catalog');
      }
    }
    const timer = window.setTimeout(() => void loadProviders(), 0);
    return () => window.clearTimeout(timer);
  }, []);

  async function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError('');
    setResult(null);
    try {
      if (providerKey === 'outlook') {
        const response = await fetch(`${API_URL}/api/accounts/outlook/oauth/start`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username, client_id: microsoftClientId.trim(), tenant: microsoftTenant.trim() || 'common' }),
        });
        const payload = (await response.json()) as { account_id?: string; user_code?: string; verification_uri?: string; detail?: string };
        if (!response.ok || !payload.account_id) throw new Error(payload.detail || 'Microsoft authorization failed');
        setOauthCode(payload.user_code ?? '');
        setOauthUrl(payload.verification_uri ?? 'https://microsoft.com/devicelogin');
        window.open(payload.verification_uri, '_blank', 'noopener,noreferrer');
        const accountIdValue = payload.account_id;
        const timer = window.setInterval(async () => {
          const statusResponse = await fetch(`${API_URL}/api/accounts/outlook/oauth/status?account_id_value=${encodeURIComponent(accountIdValue)}`, { cache: 'no-store' });
          const status = (await statusResponse.json()) as { status?: string; folder_count?: number; detail?: string; error?: string };
          if (status.status === 'connected') {
            window.clearInterval(timer);
            setResult({ connected: true, folder_count: status.folder_count ?? 0, credential_saved: true });
            setPending(false);
          } else if (status.status === 'failed' || !statusResponse.ok) {
            window.clearInterval(timer);
            setError(status.error || status.detail || 'Microsoft authorization failed');
            setPending(false);
          }
        }, 2000);
        return;
      }
      const response = await fetch(`${API_URL}/api/accounts/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider: providerKey,
          username,
          password,
          save_to_keyring: saving,
        }),
      });
      const payload = (await response.json()) as Partial<Result> & {
        detail?: string;
      };
      if (!response.ok) throw new Error(payload.detail || 'Connection failed');
      setResult({
        connected: payload.connected === true,
        folder_count: payload.folder_count ?? 0,
        credential_saved: payload.credential_saved === true,
      });
      setPassword('');
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

  return (
    <main className="min-h-screen bg-background px-5 py-8 text-foreground">
      <div className="mx-auto max-w-5xl">
        <Link
          href="/"
          className="inline-flex items-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft size={16} /> Back to overview
        </Link>
        <div className="mt-8 grid gap-6 lg:grid-cols-[1fr_340px]">
          <section className="panel">
            <p className="eyebrow">Account connection</p>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight">
              Connect {provider?.display_name ?? 'mail account'} safely
            </h1>
            <p className="mt-2 max-w-xl text-sm leading-6 text-muted-foreground">
              The test uses encrypted IMAP and lists folders only. It does not
              fetch message content, modify folders, or send mail.
            </p>
            <form className="mt-7 space-y-5" onSubmit={submit}>
              <label className="block" htmlFor="mail-provider">
                <span className="mb-2 block text-sm font-semibold">
                  Mail provider
                </span>
                <select
                  id="mail-provider"
                  value={providerKey}
                  onChange={(event) => {
                    setProviderKey(event.target.value);
                    setResult(null);
                    setError('');
                  }}
                  className="h-10 w-full rounded-lg border bg-background px-3 text-sm"
                >
                  {providers.map((item) => (
                    <option key={item.key} value={item.key}>
                      {item.display_name}
                      {item.connectable ? '' : ' — setup required'}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block" htmlFor="mail-username">
                <span className="mb-2 block text-sm font-semibold">
                  Email address or provider username
                </span>
                <Input
                  id="mail-username"
                  autoComplete="username"
                  inputMode="email"
                  required
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  placeholder="account@web.de"
                  className="h-10"
                />
              </label>
              {providerKey === 'outlook' ? <div className="grid gap-4">
                <label className="block" htmlFor="microsoft-client-id"><span className="mb-2 block text-sm font-semibold">Microsoft Entra application client ID</span><Input id="microsoft-client-id" required value={microsoftClientId} onChange={(event) => setMicrosoftClientId(event.target.value)} placeholder="00000000-0000-0000-0000-000000000000" /></label>
                <label className="block" htmlFor="microsoft-tenant"><span className="mb-2 block text-sm font-semibold">Tenant</span><Input id="microsoft-tenant" required value={microsoftTenant} onChange={(event) => setMicrosoftTenant(event.target.value)} placeholder="common" /></label>
                <p className="text-xs leading-5 text-muted-foreground">Register a public client application, enable device-code flow, and grant delegated IMAP.AccessAsUser.All and SMTP.Send permissions. Use <strong>common</strong> for personal Outlook/Hotmail accounts.</p>
                {oauthCode && <Alert><KeyRound /><AlertTitle>Enter code {oauthCode}</AlertTitle><AlertDescription><a className="underline" href={oauthUrl} target="_blank" rel="noreferrer">Open Microsoft device login</a>. This page will confirm the connection automatically.</AlertDescription></Alert>}
              </div> : <label className="block" htmlFor="mail-password">
                <span className="mb-2 block text-sm font-semibold">
                  {provider?.credential_label ?? 'Password'}
                </span>
                <span className="relative block">
                  <Input
                    id="mail-password"
                    autoComplete="current-password"
                    required
                    type={visible ? 'text' : 'password'}
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    className="h-10 pr-10"
                  />
                  <button
                    type="button"
                    aria-label={visible ? 'Hide password' : 'Show password'}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground"
                    onClick={() => setVisible(!visible)}
                  >
                    {visible ? <EyeOff size={17} /> : <Eye size={17} />}
                  </button>
                </span>
              </label>}
              {providerKey !== 'outlook' && <div className="flex gap-3 rounded-xl border bg-secondary/30 p-4">
                <input
                  id="save-credential"
                  type="checkbox"
                  checked={saving}
                  onChange={(event) => setSaving(event.target.checked)}
                  className="mt-0.5 size-4"
                />
                <label htmlFor="save-credential" className="cursor-pointer">
                  <span className="block text-sm font-semibold">
                    Save in Windows Credential Manager
                  </span>
                  <span className="mt-1 block text-xs leading-5 text-muted-foreground">
                    Recommended. The password is never written to project files,
                    browser storage, or logs.
                  </span>
                </label>
              </div>}
              {error && (
                <Alert variant="destructive">
                  <Server />
                  <AlertTitle>Connection could not be verified</AlertTitle>
                  <AlertDescription>
                    {error}. Follow the provider instructions and confirm that
                    the local API is running.
                  </AlertDescription>
                </Alert>
              )}
              {result && (
                <Alert className="border-safe/30 bg-safe-soft">
                  <CheckCircle2 className="text-safe" />
                  <AlertTitle>Secure connection verified</AlertTitle>
                  <AlertDescription>
                    {result.folder_count} folders are accessible. Credential
                    saved: {result.credential_saved ? 'yes' : 'no'}.
                    {result.credential_saved && (
                      <Link
                        className="ml-1 font-semibold text-safe underline"
                        href={`/full-scan?provider=${providerKey}`}
                      >
                        Continue to full mailbox scan
                      </Link>
                    )}
                  </AlertDescription>
                </Alert>
              )}
              <Button
                type="submit"
                size="lg"
                disabled={
                  pending ||
                  !username ||
                  (providerKey === 'outlook' ? !microsoftClientId : !password) ||
                  provider?.connectable === false
                }
                className="h-10 px-4"
              >
                {pending ? (
                  <Loader2 className="animate-spin" />
                ) : (
                  <LockKeyhole />
                )}
                {pending
                  ? providerKey === 'outlook' ? 'Waiting for Microsoft…' : 'Testing encrypted connection…'
                  : providerKey === 'outlook' ? 'Connect with Microsoft OAuth' : 'Test secure connection'}
              </Button>
            </form>
          </section>
          <aside className="space-y-4">
            <div className="panel">
              <span className="grid size-10 place-items-center rounded-xl bg-safe text-white">
                <ShieldCheck size={20} />
              </span>
              <h2 className="mt-4 font-semibold">Read-only guarantee</h2>
              <ul className="mt-3 space-y-3 text-sm text-muted-foreground">
                <li>✓ TLS on port 993</li>
                <li>✓ No SMTP access</li>
                <li>✓ No delete, move, or flag commands</li>
                <li>✓ Generic, redacted errors</li>
              </ul>
            </div>
            <div className="panel">
              <div className="flex items-center gap-2 font-semibold">
                <KeyRound size={17} className="text-brand" /> Before connecting
              </div>
              <ul className="mt-3 list-disc space-y-2 pl-5 text-sm leading-6 text-muted-foreground">
                {provider?.instructions.map((instruction) => (
                  <li key={instruction}>{instruction}</li>
                ))}
              </ul>
              {provider?.imap_host && (
                <p className="mt-3 text-xs text-muted-foreground">
                  IMAP: {provider.imap_host}:{provider.imap_port} ·
                  Authentication: {provider.auth_mode.replace('_', ' ')}
                </p>
              )}
              {provider?.help_url && (
                <a
                  href={provider.help_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-3 inline-flex items-center gap-1 text-sm font-semibold text-primary hover:underline"
                >
                  Official setup guide <ExternalLink size={14} />
                </a>
              )}
              {provider?.connectable === false && (
                <Alert variant="destructive" className="mt-4">
                  <AlertTitle>Additional connector required</AlertTitle>
                  <AlertDescription>
                    Password login is disabled to avoid an insecure or
                    non-functional connection.
                  </AlertDescription>
                </Alert>
              )}
            </div>
          </aside>
        </div>
      </div>
    </main>
  );
}
