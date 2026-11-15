import { describe, expect, it } from 'vitest'
import type { Flag, Run } from './api'
import { FLAG_CODES, atRisk, dueLabel, dueText, groupOf, outcome, problemImpact, problemLabel } from './bills'

const flag = (code: string, amount: string | null = null, quantity: string | null = null): Flag => ({ code, detail: '', amount, quantity })

function run(sample: string, flags: Flag[], total: string, over: Partial<Run> = {}): Run {
  return {
    run_id: `r-${sample}`, sample, invoice_ref: `${sample}-x`, mode: 'replay', model: 'claude-opus-5-5', status: flags.length ? 'exception' : 'ready',
    paused: true, reason: '', metrics: null, entry_id: null, extraction: null, source_checks: {}, email_draft: null, seconds: null,
    due_date: null, mirror: null, flags,
    pause: { invoice_ref: `${sample}-x`, status: flags.length ? 'exception' : 'ready', flags, approver: 'clerk', proposal: { lines: [] }, explanation: '', account_suggestion: null, controller_only: false, total },
    ...over,
  } as Run
}

describe('plain words for what the checks found', () => {
  it('has a label a bookkeeper would read for every flag code the rules emit', () => {
    // the 11 codes in src/ledger_desk (grep of Flag("..."), 2026-11-14)
    expect(FLAG_CODES).toEqual([
      'BANK_CHANGED', 'CREDIT_MEMO_UNREFERENCED', 'DUPLICATE', 'PO_NOT_FOUND', 'PRICE_VARIANCE', 'QTY_OVER_RECEIVED',
      'SOURCE_NOT_FOUND', 'SUSPICIOUS_TEXT', 'TOTALS_MISMATCH', 'UNUSUAL_AMOUNT', 'VENDOR_NOT_FOUND',
    ])
    for (const code of FLAG_CODES) {
      const label = problemLabel(code)
      expect(label).not.toBe(code)
      expect(label).not.toMatch(/_/)
    }
    expect(problemLabel('BANK_CHANGED')).toBe('Asks to be paid into a new bank account')
    expect(problemLabel('SOMETHING_NEW')).toBe('SOMETHING_NEW') // an unknown code is shown as it is, never hidden
  })

  it('says what each problem is worth in dollars, or in units when no price is stated', () => {
    expect(problemImpact(flag('PRICE_VARIANCE', '200.00'), '2100.00')).toBe('$200.00 over the agreed price')
    // the rules store the gap as a positive number either way (rules.py _arithmetic), so the wording says nothing about direction
    expect(problemImpact(flag('TOTALS_MISMATCH', '90.00'), '755.00')).toBe('$90.00 difference between the lines and the printed total')
    expect(problemImpact(flag('DUPLICATE'), '462.00')).toBe('$462.00 would be paid twice')
    expect(problemImpact(flag('BANK_CHANGED'), '860.00')).toBe('$860.00 at risk until the bank account is confirmed')
    expect(problemImpact(flag('UNUSUAL_AMOUNT', '1870.00'), '2950.00')).toBe('$1,870.00 above the usual bill')
    expect(problemImpact(flag('UNUSUAL_AMOUNT', '-700.00'), '380.00')).toBe('$700.00 below the usual bill') // total minus the average (rules.py)
    expect(problemImpact(flag('QTY_OVER_RECEIVED', null, '20'), '504.00')).toBe('20 more than was delivered')
    expect(problemImpact(flag('VENDOR_NOT_FOUND'), '189.00')).toBeNull()
  })
})

describe('money at risk, caught before paying', () => {
  it('adds stated overcharges, a bill paid twice and a payment to an unconfirmed account, and nothing else', () => {
    const runs = [
      run('03', [flag('PRICE_VARIANCE', '200.00')], '2100.00'),
      run('04', [flag('TOTALS_MISMATCH', '90.00')], '755.00'),
      run('06', [flag('QTY_OVER_RECEIVED', null, '20')], '504.00'),
      run('07', [flag('DUPLICATE')], '462.00'),
      run('08', [flag('BANK_CHANGED')], '860.00'),
      run('10', [flag('UNUSUAL_AMOUNT', '1870.00')], '2950.00'), // may be a real cold month: shown, not counted
      run('09', [], '1140.00'),
    ]
    const r = atRisk(runs)
    expect(r.total).toBe('1612.00') // 200 + 90 + 462 + 860
    expect(r.bills).toBe(4)
    expect(r.unpriced).toEqual(['20 more than was delivered'])
  })

  it('keeps counting what was rejected, and stops when someone pays despite the flag', () => {
    // review 2026-11-14: the first version dropped to $0 as the bookkeeper rejected the bad bills
    const rejected = run('07', [flag('DUPLICATE')], '462.00', { paused: false, pause: null, status: 'rejected', extraction: { total: '462.00' } as Run['extraction'] })
    expect(atRisk([rejected]).total).toBe('462.00')
    const paidAnyway = run('03', [flag('PRICE_VARIANCE', '200.00')], '2100.00', { paused: false, pause: null, status: 'posted' })
    expect(atRisk([paidAnyway]).total).toBe('0.00')
    const approvedButFailed = run('03', [flag('PRICE_VARIANCE', '200.00')], '2100.00', { paused: false, pause: null, status: 'post_failed' })
    expect(atRisk([approvedButFailed]).total).toBe('0.00')
  })

  it('counts a bill once: the whole bill when it should not be paid at all, never a credit as a negative', () => {
    expect(atRisk([run('x', [flag('PRICE_VARIANCE', '200.00'), flag('BANK_CHANGED')], '2100.00')]).total).toBe('2100.00')
    expect(atRisk([run('y', [flag('BANK_CHANGED')], '-200.00')]).total).toBe('200.00')
  })
})

describe('which list a bill belongs in', () => {
  it('puts clean bills in ready, flagged or held bills in needs a look, and decided bills in done', () => {
    expect(groupOf(run('09', [], '1140.00'))).toBe('ready')
    expect(groupOf(run('08', [flag('BANK_CHANGED')], '860.00'))).toBe('needs')
    expect(groupOf(run('09', [], '1140.00'), 'on_hold')).toBe('needs')
    expect(groupOf(run('09', [], '1140.00', { paused: false, pause: null, status: 'posted' }))).toBe('done')
    expect(groupOf(run('09', [], '1140.00', { paused: false, pause: null, status: 'rejected' }))).toBe('done')
    // not booked, so not done: the review found these shown as "Approved and booked"
    expect(groupOf(run('09', [], '1140.00', { paused: false, pause: null, status: 'post_failed' }))).toBe('needs')
    expect(groupOf(run('09', [], '1140.00', { paused: false, pause: null, status: 'failed' }))).toBe('needs')
  })

  it('says where a decided bill ended up, QuickBooks included', () => {
    const base = { paused: false, pause: null, status: 'posted', entry_id: 41 } as Partial<Run>
    expect(outcome(run('09', [], '1140.00', { ...base, mirror: { status: 'mirrored', entity: 'Bill', id: '147', doc_number: 'UTL-4411', created: true, total: 1140 } })))
      .toBe('Approved · in QuickBooks as Bill 147')
    expect(outcome(run('05', [], '-200.00', { ...base, mirror: { status: 'mirrored', entity: 'VendorCredit', id: '145', doc_number: 'CM-PKG-0412', created: true, total: 200 } })))
      .toBe('Approved · in QuickBooks as Vendor credit 145')
    expect(outcome(run('09', [], '1140.00', { ...base, mirror: { status: 'failed', error: 'QuickBooksError: 503' } })))
      .toBe('Approved and booked · not in QuickBooks: QuickBooksError: 503')
    expect(outcome(run('09', [], '1140.00', base))).toBe('Approved and booked')
    expect(outcome(run('09', [], '1140.00', { paused: false, pause: null, status: 'rejected' }))).toBe('Rejected')
    expect(outcome(run('09', [], '1140.00', { paused: false, pause: null, status: 'post_failed' }))).toBe('Approved, but booking failed: nothing was posted')
    expect(outcome(run('09', [], '1140.00', { paused: false, pause: null, status: 'failed' }))).toBe('Could not be read')
  })
})

describe('due dates', () => {
  it('reads an ISO date as a calendar day, not as midnight UTC (which is the day before in California)', () => {
    expect(dueLabel('2026-12-01')).toBe('Dec 1, 2026')
    expect(dueLabel('2026-11-04')).toBe('Nov 4, 2026')
    expect(dueLabel(null)).toBe('')
  })
})

describe('the due column', () => {
  it('shows a date to pay by, except for a credit and for a bill that was already paid', () => {
    expect(dueText(run('09', [], '1140.00', { due_date: '2026-11-25' }))).toBe('Nov 25, 2026')
    expect(dueText(run('05', [], '-200.00', { due_date: null }))).toBe('credit')
    expect(dueText(run('07', [flag('DUPLICATE')], '462.00', { due_date: '2026-11-27' }))).toBe('already paid')
    expect(dueText(run('11', [flag('VENDOR_NOT_FOUND')], '189.00', { due_date: null }))).toBe('')
  })
})
