// Browser tests for the bill desk: the queue reads the 13 sample bills, the walkthrough opens each step's bill
// and its suggested steps go through the approval rules, and How it works shows the numbers the generated
// site data holds. Against the real API in replay mode (playwright.config.ts). Third-party requests are
// blocked, so nothing here depends on the network. Each test is a new visitor with a fresh session.
import { readFileSync } from 'node:fs'
import { expect, test, type Page } from '@playwright/test'

const SITE = JSON.parse(readFileSync(new URL('../src/site-data.json', import.meta.url), 'utf-8'))
const errors = new WeakMap<Page, string[]>()

test.beforeEach(async ({ context, page }) => {
  await context.route((url) => url.hostname !== '127.0.0.1', (route) => route.abort())
  const list: string[] = []
  page.on('pageerror', (e) => list.push(e.message))
  errors.set(page, list)
})

test.afterEach(async ({ page }) => {
  expect(errors.get(page)).toEqual([])
})

/** The queue has read every sample bill (the last Review button is enabled once reading ends). */
async function queueRead(page: Page) {
  await page.goto('/')
  await expect(page.getByRole('button', { name: 'Review REP-3307' })).toBeEnabled({ timeout: 60_000 })
}

const sideways = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)

test('the queue reads all 13 bills and sorts them, with no sideways scroll', async ({ page }) => {
  await queueRead(page)
  await expect(page.getByRole('region', { name: 'Needs a look (8)' })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Ready to approve (5)' })).toBeVisible()
  await expect(page.getByRole('group', { name: 'Caught before paying' })).toContainText('$1,612.00')
  expect(await sideways(page)).toBeLessThanOrEqual(0)
})

test('the walkthrough opens each step on its bill, and the suggested steps go through the rules', async ({ page }) => {
  await queueRead(page)
  await page.getByRole('button', { name: /Walk through a morning in accounts payable/ }).click()
  const tour = page.getByRole('complementary', { name: 'Walkthrough' })
  // the bill's buttons are looked up inside the desk: the system map lower on the page repeats the suggested step
  const desk = page.locator('#desk')
  await expect(tour).toContainText('Step 1 of 6')
  await expect(tour).toContainText(`This week's ${SITE.recorded.n} bills are done`)

  await tour.getByRole('button', { name: 'Next' }).click()
  await expect(page.getByRole('cell', { name: 'UTL-4411', exact: true }).first()).toBeVisible()

  await tour.getByRole('button', { name: 'Next' }).click()
  await expect(page.getByRole('cell', { name: 'PKG-20817', exact: true }).first()).toBeVisible()
  await expect(desk.getByRole('button', { name: 'Approve against credit CM-PKG-0412' })).toBeVisible()

  await tour.getByRole('button', { name: 'Next' }).click()
  await expect(page.getByRole('cell', { name: 'DAI-5521', exact: true }).first()).toBeVisible()
  await desk.getByRole('button', { name: 'Reject as already paid' }).click()
  await expect(page.locator('.verdict')).toHaveText('Rejected')

  await tour.getByRole('button', { name: 'Next' }).click()
  await expect(page.getByRole('cell', { name: 'REP-3307', exact: true }).first()).toBeVisible()
  await desk.getByRole('button', { name: 'Approve', exact: true }).click()
  await expect(page.getByRole('alert')).toHaveText('403: only the controller may approve a bank change')
  await desk.getByRole('button', { name: 'Hold until the new bank account is confirmed' }).click()
  await expect(page.getByRole('region', { name: 'Suggested next step' })).toContainText('On hold.')
  expect(await sideways(page)).toBeLessThanOrEqual(0)

  await tour.getByRole('button', { name: 'Next' }).click()
  await expect(page.getByRole('heading', { name: 'Audit trail' })).toBeVisible()
  await tour.getByRole('button', { name: 'Finish' }).click()
  await expect(tour).toBeHidden()
})

test('How it works shows the measured numbers from the generated site data', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'How it works' }).click()
  const std = SITE.evals.find((r: { model: string; tier: string }) => r.model !== 'scripted' && r.tier === 'standard')
  await expect(page.getByText(/fields read correctly/)).toContainText(`${std.fields_correct} of ${std.fields} fields read correctly`)
  await expect(page.getByRole('table', { name: 'Where the AI helps' })).toBeVisible()
  expect(await sideways(page)).toBeLessThanOrEqual(0)
})
