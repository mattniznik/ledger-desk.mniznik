// The browser's client for the ledger-desk app API (src/ledger_desk/api.py). The visitor session
// is created on first use and kept in localStorage; it goes in the X-Session-Id header on every
// call. If the API no longer knows the stored session (expired, or the database was reset), the
// client starts a new one once and retries.

import { SITE } from './site'

export type Sample = {
  id: string
  vendor_name: string
  number: string
  total: string
  document: 'pdf' | 'photo'
  what_is_wrong: string
  replay: boolean
}

export type Flag = { code: string; detail: string; amount: string | null; quantity: string | null }
export type EntryLine = { account: string; debit: string; credit: string }
export type AccountSuggestion = { account: string | null; suggested: string | null; check: string; source: string | null; reason: string }

export type Pause = {
  invoice_ref: string
  status: string
  flags: Flag[]
  approver: 'clerk' | 'controller'
  proposal: { lines: EntryLine[]; note?: string }
  explanation: string
  account_suggestion: AccountSuggestion | null
  controller_only: boolean
  total: string
}

export type Metrics = {
  model_calls: number
  input_tokens: number
  cache_write_tokens: number
  cache_read_tokens: number
  output_tokens: number
  cost_usd: number | null
}

export type Run = {
  run_id: string
  sample: string
  invoice_ref: string
  mode: 'replay' | 'scripted'
  model: string
  status: string
  paused: boolean
  pause: Pause | null
  reason: string
  metrics: Metrics | null
  entry_id: number | null
  extraction: Extraction | null
  source_checks: Record<string, 'ok' | 'missing' | 'not_checked'>
  email_draft: { subject: string; body: string } | null
  seconds: number | null
  due_date: string | null
  mirror: Mirror | null
  flags: Flag[] // what the checks found, kept after the decision (the pause holds them only while waiting)
  held: boolean // on hold: waiting for something outside the app (a corrected bill, a phone call)
  next_step: NextStep | null // what a finance team would do about the problem, while the bill waits (playbook.py)
  lookups: Lookup[] // each lookup the agent made: the tool, its input, a one-line result (agent.lookup_result)
}

export type Lookup = { tool: string; input: Record<string, string>; result: string; ok: boolean }

// A suggested hold or reject (or an approval when a credit already settles it), worked out by code from
// what the checks found; the person presses the button and the API's rules still apply
export type NextStep = {
  code: string
  decision: 'hold' | 'reject' | 'approve'
  action: string
  why: string
  then: string
  reason: string
  also: string[]
}

// The QuickBooks sandbox copy of an approved bill (api.py run_view, workflow mirror node); null when
// the API runs without the mirror or the bill is not approved yet.
export type Mirror =
  | { status: 'mirrored'; entity: 'Bill' | 'VendorCredit'; id: string; doc_number: string; created: boolean; total: number }
  | { status: 'failed'; error: string }

export type Extraction = {
  vendor_name: string
  number: string
  date: string
  total: string
  po: string | null
  remit_bank: string
  remit_account_last4: string
  lines: { description: string; quantity: string; unit_price: string; amount: string }[]
  kind?: 'invoice' | 'credit_memo'
  sources?: Record<string, string> // each key field's text as Claude read it from the document
}

export type InvoiceRow = { id: number; number: string; vendor_name: string; status: string; total: string; run_id: string | null; flags: string[] }
export type AuditEntry = { id: number; session_id: string; at: string; actor: string; action: string; entity: string; detail: Record<string, unknown>; prev_hash: string; hash: string }
export type Verify = { intact: boolean; rows: number; first_bad_id: number | null }
export type Decision = { role: 'clerk' | 'controller'; decision: 'approve' | 'reject' | 'hold'; reason?: string; phone_confirmed?: boolean }

export type FlagScore = { tp: number; fp: number; fn: number; precision: number | null; recall: number | null }
export type EvalSummary = {
  cases: number
  end_result: { exact: number; status_ok: number; failed: string[]; known_limits: string[] }
  flags: Record<string, FlagScore>
  reading: Record<'pdf' | 'photo', { cases: number; fields: number; fields_correct: number }>
  account: { graded: number; top1: number }
  safety: { graded: number; passed: number }
  cost: { usd: number | null; per_invoice_usd: number | null }
  time: { seconds: number; per_invoice_seconds: number }
  errors: string[]
}
export type EvalRun = { name: string; version: string; tier: string; model: string; date: string; proves: string; summary: EvalSummary }
export type EvalCase = { id: string; document: string; exact: boolean; known_limit: boolean; reading_wrong: string[]; status: string }

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

const SESSION_KEY = 'ledger-desk-session'

// Locally the dev server proxies /api to the API. Deployed, the page and the API are on two hostnames, so the build
// sets VITE_API_BASE to the API's address (docs/DEPLOY.md) and the API's CORS allows only the page's origin.
export function createClient(fetchImpl: typeof fetch = fetch, storage: Storage = localStorage, base = import.meta.env.VITE_API_BASE || '/api') {
  async function newSession(): Promise<string> {
    const r = await fetchImpl(`${base}/sessions`, { method: 'POST' })
    const id = (await r.json()).session_id as string
    storage.setItem(SESSION_KEY, id)
    return id
  }

  async function call<T>(path: string, init: RequestInit = {}, retried = false): Promise<T> {
    const sid = storage.getItem(SESSION_KEY) ?? (await newSession())
    const r = await fetchImpl(`${base}${path}`, { ...init, headers: { 'Content-Type': 'application/json', 'X-Session-Id': sid } })
    const body = await r.json().catch(() => ({}))
    if (r.status === 404 && !retried && String(body.detail ?? '').startsWith('no such session')) {
      storage.removeItem(SESSION_KEY)
      return call<T>(path, init, true)
    }
    if (!r.ok) throw new ApiError(r.status, body.detail ?? r.statusText)
    return body as T
  }

  return {
    samples: async () => ((await (await fetchImpl(`${base}/samples`)).json()).samples as Sample[]),
    evals: async () => ((await (await fetchImpl(`${base}/evals`)).json()).runs as EvalRun[]),
    evalRun: async (name: string) => (await (await fetchImpl(`${base}/evals/${encodeURIComponent(name)}`)).json()) as EvalRun & { cases: EvalCase[] },
    invoices: async () => (await call<{ invoices: InvoiceRow[] }>('/invoices')).invoices,
    startRun: (invoice: string, mode: 'replay' | 'scripted' = 'replay') => call<Run>('/runs', { method: 'POST', body: JSON.stringify({ invoice, mode }) }),
    run: (id: string) => call<Run>(`/runs/${id}`),
    document: async (id: string): Promise<Blob> => {
      const sid = storage.getItem(SESSION_KEY) ?? (await newSession())
      const r = await fetchImpl(`${base}/runs/${id}/document`, { headers: { 'X-Session-Id': sid } })
      if (!r.ok) throw new ApiError(r.status, 'the document could not be loaded')
      return r.blob()
    },
    decide: (id: string, d: Decision) => call<Run>(`/runs/${id}/decision`, { method: 'POST', body: JSON.stringify(d) }),
    audit: async () => (await call<{ entries: AuditEntry[] }>('/audit')).entries,
    verify: () => call<Verify>('/audit/verify'),
    tamper: () => call<{ edited_id: number }>('/audit/tamper', { method: 'POST' }),
    // forget this visitor's session: the next call starts a new one, with fresh copies of the bills
    reset: () => storage.removeItem(SESSION_KEY),
  }
}

export type Client = ReturnType<typeof createClient>

export function usd(value: string | number): string {
  const n = Number(value)
  const s = Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  return n < 0 ? `-$${s}` : `$${s}`
}

export function modeLabel(run: Pick<Run, 'mode' | 'model'>): string {
  return run.mode === 'replay' ? `Replay of a real Claude run (${run.model}, recorded ${SITE.recorded.date})` : 'Scripted: no model, built from the answer key'
}
