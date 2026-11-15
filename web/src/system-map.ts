// The system map's pure part: the graph of the bill workflow (the bill, the reading, the source check, the checks,
// the account check, the agent and its read-only lookups, the suggested next step, the person, the signature, the
// books, the QuickBooks copy, the audit trail and the three ways a bill ends), and which node and edge each step of
// a run lights, with a caption. No React, no DOM: system-map.test.ts checks it. shared/SystemMap.tsx draws it.
//
// The steps come from a recorded run (site-data.json, where the export replayed each recorded run through today's
// code for its lookups' real results) or from the run the desk shows (the API's run view). Every number in a
// caption comes from the run or from site-data.json; none is typed here.

import type { Run } from './api'
import { amount, controllerFrom, flagWords, money, SITE, type RecordedRun } from './site'

export type NodeKind = 'person' | 'edge' | 'server' | 'gate' | 'agent' | 'model' | 'tool' | 'source' | 'rules' | 'outcome'
export type MapNode = { id: string; kind: NodeKind; label: string; sub: string; info: string }
export type MapEdge = { id: string; from: string; to: string }

export const TOOLS = ['get_purchase_order', 'get_receipts', 'get_vendor', 'get_bills', 'draft_vendor_email']
const TOOL_LABEL: Record<string, string> = {
  get_purchase_order: 'Purchase order',
  get_receipts: 'Deliveries',
  get_vendor: 'Vendor record',
  get_bills: 'Paid bills',
  draft_vendor_email: 'Draft email',
}
const TOOL_INFO: Record<string, string> = {
  get_purchase_order: 'A purchase order with its lines and the prices agreed, read from the books.',
  get_receipts: 'What was delivered against a purchase order, read from the books.',
  get_vendor: "The vendor's record, with the bank account on file, read from the books.",
  get_bills: "The vendor's paid bills, to find a copy that was already paid.",
  draft_vendor_email: 'A draft email to the vendor, saved for a person and never sent.',
}
export const toolLabel = (t: string) => TOOL_LABEL[t] ?? t

/* ---------------------------------------------------------------- the graph */

export function mapGraph(): { nodes: MapNode[]; edges: MapEdge[] } {
  const p = SITE.policies
  const nodes: MapNode[] = [
    { id: 'bill', kind: 'person', label: 'The bill', sub: 'PDF or phone photo', info: 'A supplier bill as it arrives: a PDF with a text layer, or a phone photo of a paper bill.' },
    {
      id: 'read',
      kind: 'model',
      label: SITE.model.name,
      sub: 'reads it, line by line',
      info: `${SITE.model.name} reads the bill into fields (vendor, tax id, number, date, lines, totals and bank details), each with the text it was read from.`,
    },
    {
      id: 'sources',
      kind: 'gate',
      label: 'Source check',
      sub: 'code: quotes in the PDF',
      info: "Code looks for each quoted line in the PDF's text layer; a value that is not there is flagged, and a phone photo is marked for a check by eye.",
    },
    {
      id: 'checks',
      kind: 'rules',
      label: `${SITE.checks} checks`,
      sub: 'code: order, delivery, paid, bank',
      info: `Plain code checks the arithmetic, the vendor, the price within ${p.price_tolerance_percent}% of the purchase order, the quantity against what was delivered and not yet billed, duplicates, the bank details on file, an unusual amount for a recurring bill, and text aimed at an AI.`,
    },
    {
      id: 'account',
      kind: 'model',
      label: 'Account suggested',
      sub: 'code checks the fit',
      info: "For a bill with no purchase order, Claude suggests the account; code accepts it only if it is in the chart of accounts and fits the vendor's category.",
    },
    {
      id: 'agent',
      kind: 'agent',
      label: 'Claude looks into it',
      sub: `read-only · ${p.max_lookups} lookups at most`,
      info: `For a bill with a problem, Claude looks things up in the books, read-only and at most ${p.max_lookups} lookups, then explains in plain words and may save a draft email; it cannot approve, book or pay.`,
    },
    ...TOOLS.map((t): MapNode => ({ id: `tool:${t}`, kind: t === 'draft_vendor_email' ? 'source' : 'tool', label: toolLabel(t), sub: t, info: TOOL_INFO[t] })),
    {
      id: 'playbook',
      kind: 'rules',
      label: 'Next step',
      sub: 'code: hold, reject, approve',
      info: 'Code works out the next step a finance team would take: hold for a corrected bill, reject a copy already paid, hold a bank change until it is confirmed by phone, or approve against a credit already sent.',
    },
    {
      id: 'person',
      kind: 'person',
      label: 'A person decides',
      sub: `controller from ${controllerFrom()}`,
      info: `A clerk or the controller decides. ${controllerFrom()} or more, equipment on the asset account and any bank change need the controller; a bank change also needs a phone call to the number on file, and overriding a flag needs a typed reason.`,
    },
    { id: 'sign', kind: 'gate', label: 'Signed approval', sub: 'Ed25519', info: 'The approval endpoint signs exactly what was approved, the lines and the approver, with a key only it holds.' },
    {
      id: 'erp',
      kind: 'server',
      label: 'Mock ERP',
      sub: 'verifies, then posts',
      info: 'The mock ERP checks the signature with the public key and posts the journal entry; it refuses anything else, and the database rejects an unbalanced entry.',
    },
    { id: 'qbo', kind: 'edge', label: 'QuickBooks sandbox', sub: 'a copy, when switched on', info: 'When switched on, a posted bill is copied to a QuickBooks Online sandbox company; a failure there leaves the posting alone.' },
    {
      id: 'audit',
      kind: 'server',
      label: 'Audit trail',
      sub: 'insert-only, chained',
      info: 'Every step, decision and reason goes into an insert-only audit log, each row chained to the one before, so an edited row is found.',
    },
    { id: 'booked', kind: 'outcome', label: 'Booked', sub: 'ready to pay', info: "Booked in the company's books, ready to pay." },
    { id: 'held', kind: 'outcome', label: 'On hold', sub: 'waiting', info: 'Waiting for something outside the app: a corrected bill, a delivery or a phone call.' },
    { id: 'rejected', kind: 'outcome', label: 'Rejected', sub: 'not paid', info: 'Closed without paying, with the reason on record.' },
  ]
  const e = (from: string, to: string): MapEdge => ({ id: `${from}>${to}`, from, to })
  const edges: MapEdge[] = [
    e('bill', 'read'),
    e('read', 'sources'),
    e('sources', 'checks'),
    e('checks', 'account'),
    e('checks', 'agent'),
    ...TOOLS.map((t) => e('agent', `tool:${t}`)),
    e('agent', 'playbook'),
    e('checks', 'playbook'),
    e('checks', 'person'),
    e('playbook', 'person'),
    e('person', 'audit'),
    e('person', 'sign'),
    e('sign', 'erp'),
    e('erp', 'qbo'),
    e('erp', 'booked'),
    e('person', 'held'),
    e('person', 'rejected'),
  ]
  return { nodes, edges }
}

/* ---------------------------------------------------------------- a run's steps */

export type MapEvent =
  | { type: 'bill'; vendor: string; number: string; total: string }
  | { type: 'read' }
  | { type: 'sources'; ok: number; missing: number; not_checked: number }
  | { type: 'checks'; flags: { code: string; amount: string | null }[] }
  | { type: 'account'; account: string | null }
  | { type: 'lookup'; tool: string; input: Record<string, string>; result: string; ok: boolean }
  | { type: 'next'; action: string; investigated: boolean }
  | { type: 'pause'; flagged: boolean; investigated: boolean; approver: 'clerk' | 'controller' | null }
  | { type: 'decision'; decision: 'approve' | 'hold' | 'reject' }
  | { type: 'posted'; entry: number | null }
  | { type: 'failed' }
  | { type: 'mirror'; ok: boolean; text: string }
  | { type: 'booked' }
  | { type: 'held' }
  | { type: 'rejected' }
  | { type: 'done'; calls: number; cost: number | null; seconds: number | null }

/** A recorded run's steps, as far as it went: to the person's decision. */
export function eventsFromRecorded(r: RecordedRun): MapEvent[] {
  const investigated = r.steps.some((s) => s.task === 'investigate')
  const ev: MapEvent[] = [
    { type: 'bill', vendor: r.vendor, number: r.number, total: r.total },
    { type: 'read' },
    { type: 'sources', ...r.source_checks },
    { type: 'checks', flags: r.flags.map((f) => ({ code: f.code, amount: f.amount })) },
  ]
  if (r.steps.some((s) => s.task === 'suggest_account')) ev.push({ type: 'account', account: r.account })
  for (const l of r.lookups) ev.push({ type: 'lookup', ...l })
  if (r.next_step) ev.push({ type: 'next', action: r.next_step.action, investigated })
  ev.push({ type: 'pause', flagged: r.flags.length > 0, investigated, approver: null })
  ev.push({ type: 'done', calls: r.calls, cost: r.cost_usd, seconds: r.seconds })
  return ev
}

const count = (checks: Record<string, string>, k: string) => Object.values(checks).filter((v) => v === k).length

/** The run the desk shows, from the API's run view: what happened so far, the decision included. */
export function eventsFromRun(run: Run): MapEvent[] {
  const ev: MapEvent[] = []
  const x = run.extraction
  if (x) ev.push({ type: 'bill', vendor: x.vendor_name, number: x.number, total: x.total }, { type: 'read' })
  const sc = run.source_checks ?? {}
  ev.push({ type: 'sources', ok: count(sc, 'ok'), missing: count(sc, 'missing'), not_checked: count(sc, 'not_checked') })
  const flags = run.flags ?? []
  ev.push({ type: 'checks', flags: flags.map((f) => ({ code: f.code, amount: f.amount })) })
  if (run.pause?.account_suggestion) ev.push({ type: 'account', account: run.pause.account_suggestion.account })
  const lookups = run.lookups ?? []
  for (const l of lookups) ev.push({ type: 'lookup', ...l })
  const investigated = lookups.length > 0 || !!run.pause?.explanation
  if (run.next_step) ev.push({ type: 'next', action: run.next_step.action, investigated })
  ev.push({ type: 'pause', flagged: flags.length > 0, investigated, approver: run.pause?.approver ?? null })
  if (run.paused && run.held) ev.push({ type: 'decision', decision: 'hold' }, { type: 'held' })
  else if (run.status === 'rejected') ev.push({ type: 'decision', decision: 'reject' }, { type: 'rejected' })
  else if (run.status === 'post_failed') ev.push({ type: 'decision', decision: 'approve' }, { type: 'failed' })
  else if (run.status === 'posted') {
    ev.push({ type: 'decision', decision: 'approve' }, { type: 'posted', entry: run.entry_id })
    const m = run.mirror
    if (m) ev.push(m.status === 'mirrored' ? { type: 'mirror', ok: true, text: `as ${m.entity === 'VendorCredit' ? 'a vendor credit' : 'Bill'} ${m.doc_number ?? m.id}` } : { type: 'mirror', ok: false, text: m.error })
    ev.push({ type: 'booked' })
  }
  return ev
}

/* ---------------------------------------------------------------- steps -> beats */

export type Tone = 'flow' | 'ok' | 'bad'
// One step of the animation: the node that lights, the edge the packet travels, the caption, and a result to write
// on a node. Only a step with an outcome (a check passed or failed, a lookup worked, the books posted) has a tone;
// waiting for the person and the run's totals stay neutral, so the person never looks approved before they decide.
export type Beat = { node: string; edge: string | null; back: boolean; tone: Tone; caption: string; note?: { node: string; text: string } }

const beat = (node: string, edge: string | null, caption: string, tone: Tone = 'flow', note?: Beat['note']): Beat =>
  note ? { node, edge, back: false, tone, caption, note } : { node, edge, back: false, tone, caption }

/** A lookup's input in a few words: the purchase order, the tax id, or the values given. */
export function lookupInput(input: Record<string, string>): string {
  if (input.po) return input.po
  if (input.tax_id) return `tax id ${input.tax_id}`
  return Object.entries(input)
    .filter(([k, v]) => v && k !== 'subject')
    .map(([, v]) => v)
    .join(', ')
}

type Memo = { agent: boolean }

function beatsOf(e: MapEvent, m: Memo): Beat[] {
  const p = SITE.policies
  const agentBeat = () => {
    m.agent = true
    return beat('agent', 'checks>agent', `Claude looks into it: read-only lookups in the books, at most ${p.max_lookups}.`)
  }
  switch (e.type) {
    case 'bill':
      return [beat('bill', null, `A bill arrives: ${e.vendor} ${e.number}, ${amount(e.total)}.`)]
    case 'read':
      return [beat('read', 'bill>read', `${SITE.model.name} reads it: vendor, lines, totals and bank details, each with the line it came from.`)]
    case 'sources': {
      const all = e.ok + e.missing + e.not_checked
      if (e.missing) return [beat('sources', 'read>sources', `${e.missing} of ${all} quotes are not in the PDF, so the reading is flagged.`, 'bad')]
      if (e.not_checked) return [beat('sources', 'read>sources', `A phone photo has no text layer: ${e.not_checked} fields are marked for a check by eye.`, 'ok')]
      return [beat('sources', 'read>sources', `Code finds every quote in the PDF: ${e.ok} of ${all}.`, 'ok')]
    }
    case 'checks':
      return e.flags.length
        ? [beat('checks', 'sources>checks', `The checks find: ${e.flags.map((f) => flagWords(f.code) + (f.amount ? ` (${amount(f.amount)})` : '')).join('; ')}.`, 'bad')]
        : [beat('checks', 'sources>checks', `All ${SITE.checks} checks pass: the order, the delivery, the paid bills, the bank details, the arithmetic.`, 'ok')]
    case 'account':
      return [beat('account', 'checks>account', `No purchase order: Claude suggests account ${e.account ?? 'none'}, and code accepts it only if it fits the vendor.`, 'ok')]
    case 'lookup': {
      const out = m.agent ? [] : [agentBeat()]
      const input = lookupInput(e.input)
      const caption =
        e.tool === 'draft_vendor_email'
          ? 'Claude saves a draft email to the vendor for a person; nothing is sent from here.'
          : `Claude asks for the ${toolLabel(e.tool).toLowerCase()}${input ? ` (${input})` : ''}: ${e.result}.`
      out.push(beat(`tool:${e.tool}`, `agent>tool:${e.tool}`, caption, e.ok ? 'ok' : 'bad', { node: `tool:${e.tool}`, text: e.result }))
      return out
    }
    case 'next': {
      const out = e.investigated && !m.agent ? [agentBeat()] : []
      out.push(beat('playbook', m.agent ? 'agent>playbook' : 'checks>playbook', `Code suggests the next step: ${e.action}.`))
      return out
    }
    case 'pause': {
      const out = e.investigated && !m.agent ? [agentBeat(), beat('playbook', 'agent>playbook', 'Code works out the next step.')] : []
      const who = e.approver === 'controller' ? 'only the controller may approve it' : e.approver === 'clerk' ? 'a clerk or the controller may approve it' : `${controllerFrom()} or more needs the controller`
      out.push(
        e.flagged
          ? beat('person', 'playbook>person', `It waits for a person, with the problem in plain words and the suggested step; ${who}.`)
          : beat('person', 'checks>person', `Every check passed: it waits for one click from a person; ${who}.`),
      )
      return out
    }
    case 'decision': {
      const said = { approve: 'Approved', hold: 'Put on hold', reject: 'Rejected' }[e.decision]
      const out = [beat('audit', 'person>audit', `${said}: the decision, who made it and the reason go into the audit trail.`)]
      if (e.decision === 'approve') out.push(beat('sign', 'person>sign', 'The approval is signed over exactly these lines and this approver.'))
      return out
    }
    case 'posted':
      return [beat('erp', 'sign>erp', `The mock ERP verifies the signature and posts${e.entry ? ` entry ${e.entry}` : ' the entry'}.`, 'ok')]
    case 'failed':
      return [beat('erp', 'sign>erp', 'The ERP refused the posting: nothing was booked.', 'bad')]
    case 'mirror':
      return [e.ok ? beat('qbo', 'erp>qbo', `Copied to the QuickBooks sandbox ${e.text}.`, 'ok') : beat('qbo', 'erp>qbo', `The QuickBooks copy failed (${e.text}); the posting stands.`, 'bad')]
    case 'booked':
      return [beat('booked', 'erp>booked', 'Booked, ready to pay.', 'ok')]
    case 'held':
      return [beat('held', 'person>held', 'On hold: it waits for what the next step asked for, still under Needs a look.')]
    case 'rejected':
      return [beat('rejected', 'person>rejected', 'Closed without paying, with the reason on record.')]
    case 'done':
      return [
        beat(
          'person',
          null,
          `This run: ${e.calls} model call${e.calls === 1 ? '' : 's'}, ${e.cost === null ? 'cost unknown' : `${money(e.cost)} at API list prices`}${e.seconds === null ? '' : `, ${e.seconds.toFixed(1)} s`}.`,
        ),
      ]
  }
}

/** Every beat of a run, in order. */
export function mapBeats(events: MapEvent[]): Beat[] {
  const m: Memo = { agent: false }
  return events.flatMap((e) => beatsOf(e, m))
}

/* ---------------------------------------------------------------- what is lit after k beats */

export type MapState = {
  active: Beat | null
  nodes: string[]
  edges: string[]
  status: Record<string, 'ok' | 'bad'>
  notes: Record<string, string>
}

export function mapState(beats: Beat[], k: number): MapState {
  const nodes = new Set<string>()
  const edges = new Set<string>()
  const status: MapState['status'] = {}
  const notes: MapState['notes'] = {}
  const upto = Math.min(k, beats.length - 1)
  for (let i = 0; i <= upto; i++) {
    const b = beats[i]
    nodes.add(b.node)
    if (b.edge) {
      edges.add(b.edge)
      for (const end of b.edge.split('>')) nodes.add(end)
    }
    if (b.tone !== 'flow') status[b.node] = b.tone
    if (b.note) notes[b.note.node] = b.note.text
  }
  return { active: upto >= 0 ? beats[upto] : null, nodes: [...nodes], edges: [...edges], status, notes }
}

/* ---------------------------------------------------------------- the tour */

// The overcharge: three lookups that each change the picture (the price agreed, the delivery, the bank details),
// then the conclusion and the draft. Its steps show what the AI adds better than any other recorded run.
export const TOUR_SAMPLE = '03'

export type TourStep = Beat & { title: string; info: string }

export function tourFor(r: RecordedRun): TourStep[] {
  const byId = new Map(mapGraph().nodes.map((x) => [x.id, x]))
  return mapBeats(eventsFromRecorded(r)).map((b) => ({ ...b, title: byId.get(b.node)?.label ?? b.node, info: byId.get(b.node)?.info ?? '' }))
}
