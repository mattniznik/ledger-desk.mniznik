// Browser tests for the page's twelve layouts and its Studio: every layout loads with no page errors and no sideways
// scroll, with the bill desk working inside it and its own How it works (under reduced motion: the dot field lists
// its steps, nothing plays on its own); the Studio opens, saves a pick and reloads into it (a map-first one too),
// closes on Esc with focus back on its button, and "Back to the default" clears the pick. Against the real API in
// replay mode (playwright.config.ts); third-party requests are blocked.
import { readFileSync } from 'node:fs'
import { expect, test, type Locator, type Page } from '@playwright/test'

const SITE = JSON.parse(readFileSync(new URL('../src/site-data.json', import.meta.url), 'utf-8'))
const KEY = 'ledger-desk-choice'
const errors = new WeakMap<Page, string[]>()

// each layout's family (body class) and the How it works view it names (studio/presets.ts)
const LAYOUTS: Record<string, { body: RegExp; how: string }> = {
  '01': { body: /\brich\b/, how: '#how canvas[role="img"]' },
  '04': { body: /\brich\b/, how: '#how .fig svg[role="img"]' },
  '05': { body: /\brich\b/, how: '#how .story' },
  '06': { body: /\brich\b/, how: '#how .player' },
  '07': { body: /\bs1\b/, how: '.flow' },
  '08': { body: /\bs2\b/, how: 'canvas[role="img"]' },
  '09': { body: /\bs3\b/, how: '.player' },
  '10': { body: /\blook-canvas\b/, how: '.lk-steps' },
  '11': { body: /\blook-waterfall\b/, how: '.lk-steps' },
  '12': { body: /\blook-workshop\b/, how: '.lk-steps' },
  '13': { body: /\blook-spec\b/, how: '.lk-steps' },
  '14': { body: /\blook-garage\b/, how: '.lk-steps' },
}
const ONE_COLUMN = new Set(['07', '08', '09'])
const FIELD = new Set(['01', '08'])

test.beforeEach(async ({ context, page }) => {
  await context.route((url) => url.hostname !== '127.0.0.1', (route) => route.abort())
  const list: string[] = []
  page.on('pageerror', (e) => list.push(e.message))
  errors.set(page, list)
})

test.afterEach(async ({ page }) => {
  expect(errors.get(page)).toEqual([])
})

/** The layout has rendered (the boot class is gone) and the desk inside it has read the sample bills. */
async function ready(page: Page) {
  await page.waitForFunction(() => !document.documentElement.classList.contains('boot'), null, { timeout: 15_000 })
  await expect(page.getByRole('button', { name: 'Review REP-3307' })).toBeEnabled({ timeout: 60_000 })
}
const sideways = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
const saved = (page: Page) => page.evaluate((k) => localStorage.getItem(k), KEY)

for (const [id, l] of Object.entries(LAYOUTS)) {
  test(`layout ${id} loads with the desk working, its How it works, the map, no errors and no sideways scroll`, async ({ page }) => {
    await page.goto(`/?layout=${id}`)
    await ready(page)
    await expect(page.locator(ONE_COLUMN.has(id) ? '.sp-btn.sp-fab' : '.nav .sp-btn.sp-nav')).toBeVisible()
    await expect(page.locator('body')).toHaveClass(l.body)
    await expect(page.locator(l.how).first()).toBeAttached()
    await expect(page.locator('.sm-n').first()).toBeAttached()
    // the problem and what this does comes before the demo, on every layout
    const ba = page.getByRole('region', { name: 'The problem and what this does' })
    await expect(ba).toBeVisible()
    const top = async (l: Locator) => (await l.boundingBox())!.y
    expect(await top(ba)).toBeLessThan(await top(page.locator('#desk')))
    if (FIELD.has(id)) {
      // reduced motion: the field shows its last frame and lists all six steps, with no Play button
      await expect(page.locator('.flist li')).toHaveCount(6)
      await expect(page.locator('.flist')).toContainText(`${SITE.field.cases.length} bills from the eval`)
      await expect(page.locator('.fplay')).toHaveCount(0)
    }
    expect(await sideways(page)).toBeLessThanOrEqual(0)
    expect(await saved(page)).toBeNull() // a link shows a layout; it does not save it
  })
}

test('a map-first layout link shows that layout, with the recorded bills beside the map', async ({ page }) => {
  await page.goto('/?layout=10')
  await ready(page)
  await expect(page.locator('body')).toHaveClass(/\blook-canvas\b/)
  await expect(page.getByRole('complementary', { name: 'Recorded bills' }).getByRole('list').getByRole('button')).toHaveCount(SITE.recorded.n)
})

test('layout 14 says how many bills were checked and need a person, and an unchecked photo field is not a failure', async ({ page }) => {
  await page.goto('/?layout=14')
  await ready(page)
  const runs = SITE.recorded.runs as { flags: unknown[]; source_checks: { missing: number; not_checked: number } }[]
  const flagged = runs.filter((r) => r.flags.length).length
  await expect(page.getByRole('heading', { level: 1 })).toHaveText(`${SITE.recorded.n} bills checked.${flagged} need a person.`)
  const sources = page.getByRole('button', { name: /^Source check:/ })
  const missing = runs.reduce((n, r) => n + r.source_checks.missing, 0)
  const photo = runs.reduce((n, r) => n + r.source_checks.not_checked, 0)
  await expect(sources).toContainText(`${photo} photo fields checked by eye`)
  if (missing === 0) await expect(sources.locator('.lk-g-st')).not.toHaveClass(/\bbad\b/)
})

test.describe('the Studio', () => {
  test('opens with all twelve layouts to pick, closes on Esc with focus back on its button', async ({ page }) => {
    await page.goto('/')
    await ready(page)
    const opener = page.locator('.sp-btn').first()
    await opener.click()
    const panel = page.getByRole('dialog', { name: 'Studio' })
    await expect(panel).toBeVisible()
    await expect(panel.locator('.sp-lay')).toHaveCount(12)
    await expect(panel.locator('.sp-lay:disabled')).toHaveCount(0)
    await page.keyboard.press('Escape')
    await expect(panel).toBeHidden()
    await expect(opener).toBeFocused()
  })

  test('Esc closes it and Tab stays inside it even after a click on its own text', async ({ page }) => {
    await page.goto('/')
    await ready(page)
    const opener = page.locator('.sp-btn').first()
    await opener.click()
    const panel = page.getByRole('dialog', { name: 'Studio' })
    await panel.locator('.sp-info').click() // focus leaves the buttons for the page itself
    await page.keyboard.press('Tab')
    expect(await page.evaluate(() => !!document.querySelector('.sp-panel')?.contains(document.activeElement))).toBe(true)
    await panel.locator('.sp-info').click()
    await page.keyboard.press('Escape')
    await expect(panel).toBeHidden()
    await expect(opener).toBeFocused()
  })

  // Picks Bills up front (01), a layout other than the default: since 2026-11-21 the default is Editorial (06), and
  // clicking the layout already on screen keeps the look on screen instead of bringing the layout's own.
  test('a pick is saved and the page reloads into it; Back to the default clears it', async ({ page }) => {
    await page.goto('/')
    await ready(page)
    await expect(page.locator('.hero-editorial')).toBeVisible()
    await page.locator('.sp-btn').first().click()
    const panel = page.getByRole('dialog', { name: 'Studio' })
    await Promise.all([page.waitForEvent('load'), panel.getByRole('button', { name: /^Bills up front/ }).click()])
    await ready(page)
    expect(JSON.parse((await saved(page)) ?? 'null')).toMatchObject({ option: '01', palette: 'coverDark', font: 'grotesk' })
    await expect(page.locator('.hero-search')).toBeVisible()
    // the Studio opens again after its own reload, so the visitor sees the pick and can keep going
    await expect(page.getByRole('dialog', { name: 'Studio' })).toBeVisible()
    await Promise.all([page.waitForEvent('load'), page.getByRole('dialog', { name: 'Studio' }).getByRole('button', { name: 'Back to the default' }).click()])
    await ready(page)
    expect(await saved(page)).toBeNull()
    await expect(page.locator('.hero-editorial')).toBeVisible()
  })

  test('a map-first layout can be picked too', async ({ page }) => {
    await page.goto('/')
    await ready(page)
    await page.locator('.sp-btn').first().click()
    const panel = page.getByRole('dialog', { name: 'Studio' })
    await Promise.all([page.waitForEvent('load'), panel.getByRole('button', { name: /^Status cards/ }).click()])
    await ready(page)
    expect(JSON.parse((await saved(page)) ?? 'null')).toMatchObject({ option: '14' })
    await expect(page.locator('body')).toHaveClass(/\blook-garage\b/)
  })
})
