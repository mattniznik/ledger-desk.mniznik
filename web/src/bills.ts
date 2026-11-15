import { type Flag, type Run, usd } from './api'

// The bill queue in the words of the people who use it: a bookkeeper and the owner or controller
// who signs off before paying. The checks themselves live in the API (src/ledger_desk/rules.py);
// this only says what they found in plain language and adds up what is at risk.

const LABELS: Record<string, string> = {
  BANK_CHANGED: 'Asks to be paid into a new bank account',
  CREDIT_MEMO_UNREFERENCED: 'Credit memo that does not say which invoice it is for',
  DUPLICATE: 'Already paid',
  PO_NOT_FOUND: 'No matching purchase order',
  PRICE_VARIANCE: 'Charged more than the purchase order price',
  QTY_OVER_RECEIVED: 'Billed for more than was delivered',
  SOURCE_NOT_FOUND: 'A value read from the bill is not on the document',
  SUSPICIOUS_TEXT: 'Contains instructions aimed at AI',
  TOTALS_MISMATCH: 'The total does not add up',
  UNUSUAL_AMOUNT: 'Much higher than the usual bill',
  VENDOR_NOT_FOUND: 'New vendor, not set up yet',
}

export const FLAG_CODES = Object.keys(LABELS).sort()

export function problemLabel(code: string): string {
  return LABELS[code] ?? code
}

const units = (q: string) => Number(q).toLocaleString('en-US')

export function problemImpact(flag: Flag, billTotal: string): string | null {
  switch (flag.code) {
    case 'PRICE_VARIANCE':
      return flag.amount ? `${usd(flag.amount)} over the agreed price` : null
    case 'TOTALS_MISMATCH': // the rules store the gap as a positive number whichever side is larger
      return flag.amount ? `${usd(Math.abs(Number(flag.amount)))} difference between the lines and the printed total` : null
    case 'UNUSUAL_AMOUNT': // the bill minus the usual amount: negative when the bill is far below it
      return flag.amount ? `${usd(Math.abs(Number(flag.amount)))} ${Number(flag.amount) < 0 ? 'below' : 'above'} the usual bill` : null
    case 'DUPLICATE':
      return `${usd(billTotal)} would be paid twice`
    case 'BANK_CHANGED':
      return `${usd(billTotal)} at risk until the bank account is confirmed`
    case 'QTY_OVER_RECEIVED':
      return flag.quantity ? `${units(flag.quantity)} more than was delivered` : null
    default:
      return null
  }
}

const cents = (v: string) => Math.round(Number(v) * 100)

// Counted, once per bill: the whole bill when it should not be paid at all (already paid, or to a
// bank account nobody has confirmed), otherwise the overcharges the checks priced. Kept after the bill
// is rejected or held (it was caught); dropped once someone approves it anyway (it is being paid).
// Not counted: an unusual amount (it may be a real cold month) and a quantity problem, which the
// checks state in units, not dollars; those are listed instead.
export function atRisk(runs: Run[]): { total: string; bills: number; unpriced: string[] } {
  let sum = 0
  let bills = 0
  const unpriced: string[] = []
  for (const r of runs) {
    if (r.status === 'posted' || r.status === 'post_failed') continue
    const flags = r.flags?.length ? r.flags : r.pause?.flags ?? []
    const total = r.pause?.total ?? r.extraction?.total ?? '0'
    const whole = flags.some((f) => f.code === 'DUPLICATE' || f.code === 'BANK_CHANGED')
    const priced = flags
      .filter((f) => (f.code === 'PRICE_VARIANCE' || f.code === 'TOTALS_MISMATCH') && f.amount)
      .reduce((a, f) => a + Math.abs(cents(f.amount as string)), 0)
    const add = whole ? Math.abs(cents(total)) : priced
    if (add > 0) {
      sum += add
      bills += 1
    }
    for (const f of flags) {
      const impact = f.code === 'QTY_OVER_RECEIVED' ? problemImpact(f, total) : null
      if (impact) unpriced.push(impact)
    }
  }
  return { total: (sum / 100).toFixed(2), bills, unpriced }
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

// "2026-12-01" -> "Dec 1, 2026", split by hand: new Date("2026-12-01") is midnight UTC, which a
// browser in California shows as Nov 30.
export function dueLabel(iso: string | null): string {
  if (!iso) return ''
  const [y, m, d] = iso.split('-').map(Number)
  return MONTHS[m - 1] ? `${MONTHS[m - 1]} ${d}, ${y}` : iso
}

// What the Due column says: the date to pay by, "credit" for a credit memo (nothing to pay) and
// "already paid" for a duplicate (paying it by its due date would be paying twice).
export function dueText(run: Run): string {
  if (Number(run.pause?.total ?? run.extraction?.total ?? 0) < 0) return 'credit'
  if (run.pause?.flags.some((f) => f.code === 'DUPLICATE')) return 'already paid'
  return dueLabel(run.due_date)
}

export type Group = 'needs' | 'ready' | 'done'

// Done means decided and settled: booked or rejected. Anything else that is not a clean bill waiting
// (a failed booking, a bill that could not be read, a hold) needs a look.
export function groupOf(run: Run, invoiceStatus?: string): Group {
  if (run.status === 'posted' || run.status === 'rejected') return 'done'
  if (run.paused && run.pause && invoiceStatus !== 'on_hold' && run.pause.flags.length === 0) return 'ready'
  return 'needs'
}

const ENTITY: Record<string, string> = { Bill: 'Bill', VendorCredit: 'Vendor credit' }

export function outcome(run: Run): string {
  if (run.status === 'rejected') return 'Rejected'
  if (run.status === 'post_failed') return 'Approved, but booking failed: nothing was posted'
  if (run.status === 'failed') return 'Could not be read'
  if (run.status !== 'posted') return run.status
  const m = run.mirror
  if (m?.status === 'mirrored') return `Approved · in QuickBooks as ${ENTITY[m.entity] ?? m.entity} ${m.id}`
  if (m?.status === 'failed') return `Approved and booked · not in QuickBooks: ${m.error}`
  return 'Approved and booked'
}
