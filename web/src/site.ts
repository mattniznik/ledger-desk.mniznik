// Every number the page shows about how well the demo works and how it was built, from site-data.json.
// scripts/export_site.py writes that file from the eval results, the recorded runs, the decision records
// and both test suites (it refuses while a test fails); nothing here is typed in. The words around the
// numbers are plain functions here, tested in site.test.ts.

import data from './site-data.json'

export type EvalRunSummary = {
  model: string
  tier: string
  cases: number
  end_result: number
  fields: number
  fields_correct: number
  pdf_fields: number
  photo_fields: number
  account_top1: number
  account_graded: number
  safe: number
  per_invoice_usd: number
  per_invoice_seconds: number
}

export type RecordedFlag = { code: string; amount: string | null; detail: string }
export type RecordedStep = { task: string; tools: string[] }
export type RecordedLookup = { tool: string; input: Record<string, string>; result: string; ok: boolean }
export type RecordedRun = {
  sample: string
  calls: number
  cost_usd: number
  seconds: number
  vendor: string
  number: string
  total: string
  status: string
  account: string | null
  flags: RecordedFlag[]
  explanation: string
  steps: RecordedStep[]
  // replayed through today's code by the export: each lookup with its real result
  lookups: RecordedLookup[]
  source_checks: { ok: number; missing: number; not_checked: number }
  next_step: { code: string; decision: string; action: string } | null
  // each model call's tokens, as the API reported them
  usage: { step: string; input: number; cache_write: number; cache_read: number; output: number; tokens: number }[]
}
export type FieldCase = { id: string; document: string; status: string; exact: boolean; safe: boolean }
export type Spread = { total: number; mean: number; median: number; min: number; max: number }
export type BuiltStep = { title: string; text: string; fact: string; url: string | null }
export type Suite = { tests: number; passed: number; failed: number; files: number }

export const SITE = data as unknown as {
  evals: EvalRunSummary[]
  policies: { controller_from: number; price_tolerance_percent: number; max_lookups: number }
  recorded: { n: number; matched: number; date: string; model_calls: number; cost_usd: Spread; seconds: Spread; runs: RecordedRun[] }
  tests: { python: Suite; web: Suite }
  model: { id: string; name: string }
  checks: number
  decisions: { number: string; title: string; file: string }[]
  built: { repo: string | null; steps: BuiltStep[]; badge: string | null; links: { label: string; url: string }[] }
  field: { file: string; cases: FieldCase[] }
}

// "$5,000": the controller's limit as the rules hold it
export const controllerFrom = () => '$' + SITE.policies.controller_from.toLocaleString('en-US')

// The real model's run on a tier (scripted runs prove the graders, not a model)
export function modelRun(tier: 'standard' | 'hard'): EvalRunSummary | undefined {
  return SITE.evals.find((r) => r.model !== 'scripted' && r.tier === tier)
}

export const money = (usd: number, digits = 4) => '$' + usd.toFixed(digits)
export const amount = (s: string | number) => '$' + Number(s).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

/** A recorded run, by sample id ("03"). */
export function runOf(sample: string): RecordedRun {
  const r = SITE.recorded.runs.find((x) => x.sample === sample)
  if (!r) throw new Error(`no recorded run for sample ${sample}`)
  return r
}

export const billTitle = (r: RecordedRun) => `${r.vendor} ${r.number}`
export const toolCount = (r: RecordedRun) => r.steps.reduce((n, s) => n + s.tools.filter((t) => t !== 'draft_vendor_email').length, 0)
export const drafted = (r: RecordedRun) => r.steps.some((s) => s.tools.includes('draft_vendor_email'))

const TOOL_WORDS: Record<string, string> = {
  get_purchase_order: 'the purchase order',
  get_receipts: 'what was delivered',
  get_vendor: 'the vendor record',
  get_bills: 'the paid bills',
}
const FLAG_WORDS: Record<string, string> = {
  BANK_CHANGED: 'asks to be paid into a new bank account',
  CREDIT_MEMO_UNREFERENCED: 'a credit memo that does not say which bill it is for',
  DUPLICATE: 'already paid',
  PO_NOT_FOUND: 'no matching purchase order',
  PRICE_VARIANCE: 'charged more than the purchase order price',
  QTY_OVER_RECEIVED: 'billed for more than was delivered',
  SOURCE_NOT_FOUND: 'a value read from the bill is not on the document',
  SUSPICIOUS_TEXT: 'contains instructions aimed at AI',
  TOTALS_MISMATCH: 'the total does not add up',
  UNUSUAL_AMOUNT: 'much higher than the usual bill',
  VENDOR_NOT_FOUND: 'a new vendor, not set up yet',
}
export const flagWords = (code: string) => FLAG_WORDS[code] ?? code.toLowerCase().replace(/_/g, ' ')
// every code the checks can raise, for the layouts that list the checks
export const FLAG_CODES = Object.keys(FLAG_WORDS)

export type LogLine = { k: string; d: string }

/** A recorded run as log lines: what was read, what the checks found, each lookup, and where it stopped. */
export function logLines(r: RecordedRun): LogLine[] {
  const lines: LogLine[] = [{ k: 'read', d: `${r.vendor} ${r.number}, ${amount(r.total)}: every key field with the line it was read from` }]
  lines.push({ k: 'check', d: r.flags.length ? r.flags.map((f) => flagWords(f.code) + (f.amount ? ` (${amount(f.amount)})` : '')).join('; ') : 'every check passed' })
  for (const s of r.steps) {
    if (s.task === 'suggest_account') lines.push({ k: 'account', d: `suggested ${r.account ?? 'none'}; code checks it against the chart` })
    for (const t of s.tools) lines.push(t === 'draft_vendor_email' ? { k: 'draft', d: 'an email to the vendor, saved for a person, not sent' } : { k: 'lookup', d: TOOL_WORDS[t] ?? t })
  }
  lines.push({ k: 'pause', d: r.flags.length ? 'waiting for a person, with the problem and a suggested next step' : 'waiting for one click from a person' })
  return lines
}

/** How it works, in six steps, for the sections that list them; sub is the short label the figures use. */
export function howSteps(): { title: string; text: string; sub: string }[] {
  const std = modelRun('standard')
  return [
    { title: 'A bill arrives', text: 'A PDF, or a phone photo of a paper bill.', sub: 'PDF or phone photo' },
    {
      title: SITE.model.name + ' reads it',
      text:
        'Vendor, lines, totals and bank details, each with the line it was read from' +
        (std ? '; ' + std.fields_correct + ' of ' + std.fields + ' fields right in the eval' : '') +
        '.',
      sub: 'fields and their source lines',
    },
    {
      title: 'Code checks it',
      text: 'Against the purchase order, what was delivered, the paid bills and the bank details on file: ' + SITE.checks + ' checks.',
      sub: SITE.checks + ' checks, in code',
    },
    { title: 'Claude looks into a problem', text: 'Read-only lookups, an explanation in plain words, an email to the vendor drafted, never sent.', sub: 'read-only lookups' },
    {
      title: 'A person decides',
      text: 'With a suggested next step. ' + controllerFrom() + ' or more, and any bank change, need the controller.',
      sub: controllerFrom() + ' or more: the controller',
    },
    {
      title: 'Booked, and logged',
      text: 'The signed approval goes to the books, and to QuickBooks when it is connected; every step is in the audit trail.',
      sub: 'signed, booked, logged',
    },
  ]
}

const plural = (k: number, one: string, many = one + 's') => k + ' ' + (k === 1 ? one : many)

export type FieldMark = { photo: boolean; flagged: boolean; exact: boolean }
export type FieldModel = { n: number; photos: number; flagged: number; clean: number; exact: number; safe: number; marks: FieldMark[]; captions: string[] }

/** The dot field: one mark per bill the eval read, in the eval's order, each with its real outcome, and a caption
 * for each of the six steps written from the counts. */
export function fieldModel(cases: FieldCase[]): FieldModel {
  const n = cases.length
  const photos = cases.filter((x) => x.document === 'photo').length
  const flagged = cases.filter((x) => x.status !== 'ready').length
  const exact = cases.filter((x) => x.exact).length
  const safe = cases.filter((x) => x.safe).length
  const clean = n - flagged
  const std = modelRun('standard')
  return {
    n,
    photos,
    flagged,
    clean,
    exact,
    safe,
    marks: cases.map((x) => ({ photo: x.document === 'photo', flagged: x.status !== 'ready', exact: x.exact })),
    captions: [
      plural(n, 'bill') + ' from the eval: ' + plural(n - photos, 'PDF') + ' and ' + plural(photos, 'phone photo'),
      SITE.model.name + ' reads every one' + (std ? ': ' + std.fields_correct + ' of ' + std.fields + ' fields right' : ''),
      'Code checks them: ' + flagged + (flagged === 1 ? ' has' : ' have') + ' a problem, ' + clean + (clean === 1 ? ' is' : ' are') + ' clean',
      'Claude looks into the ' + plural(flagged, 'problem bill') + ', read-only, and drafts the emails',
      'A person decides: ' + clean + ' wait for one click, ' + flagged + ' come with a suggested next step',
      exact + ' of ' + n + ' ended exactly as their answer key says; ' + safe + ' of ' + n + ' booked nothing without a person',
    ],
  }
}

/** One recorded run as the six steps of How it works, from the export's record of it. */
export type Walk =
  | { kind: 'bill'; vendor: string; number: string; total: string }
  | { kind: 'read'; ok: number; missing: number; notChecked: number; of: number }
  | { kind: 'checks'; flags: { code: string; words: string; amount: string | null }[]; checks: number }
  | { kind: 'lookups'; lookups: RecordedLookup[]; drafted: boolean }
  | { kind: 'decide'; next: string; controllerFrom: string }
  | { kind: 'cost'; calls: number; lookups: number; maxLookups: number; costUsd: number; seconds: number }

export function walkOf(r: RecordedRun): Walk[] {
  const sc = r.source_checks
  const lookups = r.lookups.filter((l) => l.tool !== 'draft_vendor_email')
  return [
    { kind: 'bill', vendor: r.vendor, number: r.number, total: r.total },
    { kind: 'read', ok: sc.ok, missing: sc.missing, notChecked: sc.not_checked, of: sc.ok + sc.missing + sc.not_checked },
    { kind: 'checks', flags: r.flags.map((f) => ({ code: f.code, words: flagWords(f.code), amount: f.amount })), checks: SITE.checks },
    { kind: 'lookups', lookups, drafted: r.lookups.some((l) => l.tool === 'draft_vendor_email') },
    { kind: 'decide', next: r.next_step ? r.next_step.action : r.flags.length ? 'Look into it' : 'Approve: every check passed', controllerFrom: controllerFrom() },
    { kind: 'cost', calls: r.calls, lookups: lookups.length, maxLookups: SITE.policies.max_lookups, costUsd: r.cost_usd, seconds: r.seconds },
  ]
}

export type HowKind = 'field' | 'pipeline' | 'story' | 'player'

/** The sentence over each animation of How it works, written from the data. */
export function howSub(kind: HowKind): string {
  const f = fieldModel(SITE.field.cases)
  return {
    field:
      'One mark per bill the eval read: a dot per PDF (' + (f.n - f.photos) + '), a square per phone photo (' + f.photos + '). Watch them narrow to the ones a person must look at. Click a step.',
    pipeline: 'The whole workflow on one figure. Claude reads and looks things up; the boxes in the accent colour are code, and a person makes the call.',
    story: 'Follow one real run through the workflow: the bill that asks to be paid into a new bank account. Scroll; the panel shows each step.',
    player: 'One recorded run at a time, step by step, with every value it produced. It plays once when it scrolls into view; click a step to stop there.',
  }[kind]
}
