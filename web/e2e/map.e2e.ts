// Browser tests for the system map and the trace on a bill: the map is drawn in every section-built and one-column
// layout (wide on a desktop, two columns on a phone) with no sideways scroll; under reduced motion it lists every
// step; the tour goes a step at a time; opening a bill in the desk puts that bill on the map; and the bill page shows
// how the bill was handled, its lookups included. Against the real API in replay mode (playwright.config.ts);
// third-party requests are blocked.
import { expect, test, type Page } from '@playwright/test'

const LAYOUTS = ['01', '04', '05', '06', '07', '08', '09']
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

async function ready(page: Page) {
  await page.waitForFunction(() => !document.documentElement.classList.contains('boot'), null, { timeout: 15_000 })
  await expect(page.getByRole('button', { name: 'Review REP-3307' })).toBeEnabled({ timeout: 60_000 })
}
const sideways = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
const map = (page: Page) => page.locator('.sm')

for (const id of LAYOUTS) {
  test(`layout ${id} draws the system map, every step listed, no sideways scroll`, async ({ page }, info) => {
    await page.goto(`/?layout=${id}`)
    await ready(page)
    await map(page).scrollIntoViewIfNeeded()
    await expect(page.getByRole('group', { name: /^System map: \d+ pieces/ })).toBeVisible()
    await expect(map(page)).toHaveClass(info.project.name === 'phone' ? /is-tall/ : /is-wide|is-tall/)
    const list = map(page).locator('details.sm-list')
    await expect(list).toHaveAttribute('open', '') // reduced motion: every step is listed
    expect(await list.locator('li').count()).toBeGreaterThanOrEqual(10)
    expect(await sideways(page)).toBeLessThanOrEqual(0)
  })
}

test('the tour goes a step at a time', async ({ page }) => {
  await page.goto('/?layout=01')
  await ready(page)
  await map(page).getByRole('button', { name: 'Take the tour' }).click()
  await expect(map(page).locator('.sm-step')).toContainText('Step 1 of')
  await map(page).getByRole('button', { name: 'Next', exact: true }).click()
  await expect(map(page).locator('.sm-step')).toContainText('Step 2 of')
})

test('opening a bill puts it on the map, and the bill page shows how it was handled', async ({ page }) => {
  await page.goto('/?layout=01')
  await ready(page)
  await page.getByRole('button', { name: 'Review REP-3307' }).click()
  const trace = page.getByRole('region', { name: 'How this bill was handled' })
  await expect(trace).toContainText('Vendor record (tax id')
  await expect(trace).toContainText('account ending 4417')
  await expect(trace).toContainText('found in the PDF')
  await expect(map(page).locator('.sm-now')).toContainText('The bill you opened: Espresso Repair Service REP-3307')
  expect(await sideways(page)).toBeLessThanOrEqual(0)
})
