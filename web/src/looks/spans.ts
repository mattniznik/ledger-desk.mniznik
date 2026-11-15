// The trace waterfall's pure part (layout 11, LookPage.tsx): one recorded run as steps - each model call with the
// tokens the API reported, the source check and the checks, each tool call in the order it ran, the next step and the
// person - each pointing at a piece of the system map. Only measured shares get a bar. Tested in spans.test.ts.

import { amount, billTitle, controllerFrom, flagWords, money, SITE, type RecordedRun } from '../site.ts'
import { lookupInput, toolLabel } from '../system-map.ts'

// What each lookup reads in the mock ERP (src/ledger_desk/agent.py: the agent's read-only tools)
export const READS: Record<string, string> = {
  get_purchase_order: "the mock ERP's purchase orders and their lines",
  get_receipts: "the mock ERP's deliveries against a purchase order",
  get_vendor: "the mock ERP's vendor record: name, tax id, bank details on file",
  get_bills: "the mock ERP's paid bills, by vendor, number or dates",
  draft_vendor_email: 'nothing in the books: it saves a draft for a person, never sent',
}

export type Span = { id: string; depth: number; kind: 'root' | 'model' | 'code' | 'tool' | 'person'; name: string; detail: string; value: string; share: number; node: string; bad: boolean; attrs: [string, string][] }

const STEP_NAME: Record<string, [string, string]> = {
  read: ['reads the bill', 'read'],
  suggest_account: ['suggests an account', 'account'],
  investigate: ['looks into it', 'agent'],
}

/** One recorded run as spans: each model call with its measured tokens, the code checks, each lookup, the next step. */
export function spansOf(r: RecordedRun): Span[] {
  const total = r.usage.reduce((n, u) => n + u.tokens, 0) || 1
  const lookups = [...r.lookups]
  const sc = r.source_checks, of = sc.ok + sc.missing + sc.not_checked
  const out: Span[] = [
    {
      id: 'root',
      depth: 0,
      kind: 'root',
      name: 'bill',
      detail: billTitle(r),
      value: `${r.seconds.toFixed(1)} s`,
      share: 1,
      node: 'bill',
      bad: false,
      attrs: [
        ['bill', billTitle(r)],
        ['total', amount(r.total)],
        ['model calls', String(r.calls)],
        ['lookups', String(r.lookups.filter((l) => l.tool !== 'draft_vendor_email').length)],
        ['tokens', total.toLocaleString('en-US')],
        ['seconds', r.seconds.toFixed(1)],
        ['cost at API list prices', money(r.cost_usd)],
      ],
    },
  ]
  r.usage.forEach((u, i) => {
    const [name, node] = STEP_NAME[u.step] ?? [u.step, 'read']
    out.push({
      id: `m${i}`,
      depth: 1,
      kind: 'model',
      name: `model · ${name}`,
      detail: SITE.model.id,
      value: `${u.tokens.toLocaleString('en-US')} tok`,
      share: u.tokens / total,
      node,
      bad: false,
      attrs: [
        ['step', u.step],
        ['input tokens', String(u.input)],
        ['cache write', String(u.cache_write)],
        ['cache read', String(u.cache_read)],
        ['output tokens', String(u.output)],
      ],
    })
    // the lookups this call asked for, in the order they ran
    for (const t of r.steps[i]?.tools ?? []) {
      const l = lookups.findIndex((x) => x.tool === t)
      if (l < 0) continue
      const [x] = lookups.splice(l, 1)
      out.push({
        id: `t${i}-${t}`,
        depth: 2,
        kind: 'tool',
        name: `tool · ${toolLabel(t).toLowerCase()}`,
        detail: `${lookupInput(x.input) || 'no input'}: ${x.result}`,
        value: x.ok ? 'ok' : 'failed',
        share: 0,
        node: `tool:${t}`,
        bad: !x.ok,
        attrs: [
          ['tool', t],
          ['input', lookupInput(x.input) || 'none'],
          ['reads', READS[t] ?? ''],
          ['returned', x.result],
        ],
      })
    }
    if (u.step === 'read') {
      out.push({
        id: 'sources',
        depth: 1,
        kind: 'code',
        name: 'code · source check',
        detail: `${sc.ok} of ${of} quoted lines found in the PDF`,
        value: sc.missing ? `${sc.missing} missing` : 'all found',
        share: 0,
        node: 'sources',
        bad: sc.missing > 0,
        attrs: [
          ['found in the PDF', String(sc.ok)],
          ['not found', String(sc.missing)],
          ['photo, by eye', String(sc.not_checked)],
        ],
      })
      out.push({
        id: 'checks',
        depth: 1,
        kind: 'code',
        name: 'code · checks',
        detail: r.flags.length ? r.flags.map((f) => flagWords(f.code)).join('; ') : 'every check passed',
        value: `${r.flags.length} flagged`,
        share: 0,
        node: 'checks',
        bad: r.flags.length > 0,
        attrs: r.flags.length ? r.flags.map((f): [string, string] => [f.code, f.detail]) : [['result', `all ${SITE.checks} checks passed`]],
      })
    }
  })
  out.push({
    id: 'next',
    depth: 1,
    kind: 'code',
    name: 'code · next step',
    detail: r.next_step ? r.next_step.action : 'approve: every check passed',
    value: r.next_step ? r.next_step.decision : 'approve',
    share: 0,
    node: 'playbook',
    bad: false,
    attrs: [['suggested', r.next_step ? r.next_step.action : 'approve: every check passed']],
  })
  out.push({ id: 'person', depth: 1, kind: 'person', name: 'a person decides', detail: 'nothing is booked until they approve', value: '', share: 0, node: 'person', bad: false, attrs: [['controller from', controllerFrom()]] })
  return out
}
