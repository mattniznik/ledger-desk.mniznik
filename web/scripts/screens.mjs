// Visual check of the web app in a real browser, at a desktop width and at a true phone width.
//
//   node web/scripts/screens.mjs <outDir> [baseUrl=http://127.0.0.1:5181/] [cdpPort=9362]
//
// Needs the app API (`uv run ledger-desk api-serve`), the dev server, and a headless Chrome with
// --remote-debugging-port. The phone is emulated through the DevTools protocol (390 css px wide,
// device pixel ratio 3, mobile, touch), not a narrowed desktop window. For each size it starts a
// fresh visitor session, waits for the bill queue to read all 13 bills, opens bill REP-3307 (08),
// tries to approve it as a clerk (the API refuses), then verifies the audit trail; on desktop it
// also approves the clean bill UTL-4411 (09) as a clerk to show the Done list. That approval goes
// to QuickBooks when the API runs with --mirror-quickbooks; the mirror finds the bill it made
// before (same number, same vendor) and writes nothing new. It saves a screenshot of each screen
// and prints the layout facts it measured (viewport, document width, horizontal overflow).

import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const [outDir = 'screens', base = 'http://127.0.0.1:5181/', port = '9362'] = process.argv.slice(2)
mkdirSync(outDir, { recursive: true })

const VIEWS = [
  { name: 'desktop-1280', width: 1280, height: 800, deviceScaleFactor: 1, mobile: false, scale: 1 },
  { name: 'phone-390', width: 390, height: 844, deviceScaleFactor: 3, mobile: true, scale: 0.5 },
]
const MOBILE_UA = 'Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36'

const target = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: 'PUT' })).json()
const ws = new WebSocket(target.webSocketDebuggerUrl)
await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject })
let seq = 0
const pending = new Map()
ws.onmessage = (m) => {
  const d = JSON.parse(m.data)
  if (d.id && pending.has(d.id)) {
    const { resolve, reject } = pending.get(d.id)
    pending.delete(d.id)
    if (d.error) reject(new Error(d.error.message))
    else resolve(d.result)
  }
}
const send = (method, params = {}) => new Promise((resolve, reject) => {
  const id = ++seq
  pending.set(id, { resolve, reject })
  ws.send(JSON.stringify({ id, method, params }))
})
const evaluate = async (expression) => (await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true })).result.value
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
async function waitFor(expression, what, ms = 20000) {
  const t = Date.now()
  while (Date.now() - t < ms) {
    if (await evaluate(expression)) return
    await sleep(150)
  }
  throw new Error(`timed out waiting for ${what}`)
}
const click = (expression) => evaluate(`(${expression}).click()`)
const button = (text) => `[...document.querySelectorAll('button')].find((b) => b.textContent.trim() === ${JSON.stringify(text)})`
const layout = () => evaluate(`({ innerWidth, scrollWidth: document.documentElement.scrollWidth, overflowX: document.documentElement.scrollWidth > innerWidth, dpr: devicePixelRatio, touch: navigator.maxTouchPoints })`)

async function shot(file, scale) {
  const { cssContentSize: size } = await send('Page.getLayoutMetrics')
  const { data } = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true, clip: { x: 0, y: 0, width: size.width, height: size.height, scale } })
  writeFileSync(join(outDir, file), Buffer.from(data, 'base64'))
  return file
}

await send('Page.enable')
await send('Runtime.enable')
const facts = {}
for (const v of VIEWS) {
  await send('Emulation.setDeviceMetricsOverride', { width: v.width, height: v.height, deviceScaleFactor: v.deviceScaleFactor, mobile: v.mobile })
  await send('Emulation.setTouchEmulationEnabled', v.mobile ? { enabled: true, maxTouchPoints: 5 } : { enabled: false }) // 0 points is refused (measured)
  if (v.mobile) await send('Emulation.setUserAgentOverride', { userAgent: MOBILE_UA })
  await send('Page.navigate', { url: base })
  await waitFor(`document.readyState === 'complete'`, 'the page')
  await evaluate('localStorage.clear()') // a fresh visitor for each size
  await send('Page.reload')
  const review = (number) => `document.querySelector('[aria-label="Review ${number}"]')`
  await waitFor(`!!${review('REP-3307')} && !${review('REP-3307')}.disabled`, 'the bill queue', 60000)
  const f = { inbox: await layout() }
  f.inbox.cards = await evaluate(`[...document.querySelectorAll('.stat')].map((c) => c.innerText.replace(/\\s+/g, ' '))`)
  await shot(`${v.name}-1-inbox.png`, v.scale)

  await click(review('REP-3307'))
  await waitFor(`!!${button('Approve')}`, 'the invoice view')
  await sleep(800) // the document is fetched separately
  f.invoice = await layout()
  f.invoice.documentShown = await evaluate(`!!(document.querySelector('.doc object, .doc img'))`)
  await shot(`${v.name}-2-invoice.png`, v.scale)

  await click(button('Approve')) // as the default role, clerk: the API must refuse a bank change
  await waitFor(`!!document.querySelector('[role=alert]')`, 'the refusal')
  f.refusal = await evaluate(`document.querySelector('[role=alert]').textContent`)
  await shot(`${v.name}-3-refused.png`, v.scale)

  await click(button('Audit trail'))
  await waitFor(`!!${button('Verify audit log')}`, 'the audit view')
  await click(button('Verify audit log'))
  await waitFor(`!!document.querySelector('[role=status]')`, 'the verify result')
  f.audit = { ...(await layout()), verify: await evaluate(`document.querySelector('[role=status]').textContent`), rows: await evaluate(`document.querySelectorAll('.audit tbody tr').length`) }
  await shot(`${v.name}-4-audit.png`, v.scale)

  if (!v.mobile) {
    await click(button('Bills'))
    await waitFor(`!!${review('UTL-4411')} && !${review('UTL-4411')}.disabled`, 'the bill queue again')
    await click(review('UTL-4411'))
    await waitFor(`!!${button('Approve')}`, 'bill UTL-4411')
    await click(button('Approve'))
    await waitFor(`!!document.querySelector('.verdict.done')`, 'the approval', 60000)
    f.approved = { verdict: await evaluate(`document.querySelector('.verdict').textContent`) }
    await shot(`${v.name}-5-approved.png`, v.scale)
    await click(button('Back to the bills'))
    await waitFor(`!!document.querySelector('[aria-label^="Done"]')`, 'the done list')
    f.done = await evaluate(`[...document.querySelectorAll('[aria-label^="Done"] tbody tr')].map((r) => r.innerText.replace(/\\s+/g, ' '))`)
    await shot(`${v.name}-6-queue-after.png`, v.scale)

    await click(button('How it works'))
    await waitFor(`!![...document.querySelectorAll('h3')].find((h) => h.textContent === 'Who it is for')`, 'how it works')
    await shot(`${v.name}-7-how.png`, v.scale)
  }
  facts[v.name] = f
}
console.log(JSON.stringify(facts, null, 2))
ws.close()
await fetch(`http://127.0.0.1:${port}/json/close/${target.id}`)

// The check: on the phone, every screen must lay out at the emulated width. A page wider than the
// phone makes the browser zoom out and shrink every word; scrollWidth alone does not show it,
// because the layout viewport grows to the content (measured 2026-11-14: 463 and 533 css px).
const problems = []
for (const v of VIEWS) {
  for (const [screen, f] of Object.entries(facts[v.name])) {
    if (f && typeof f === 'object' && 'innerWidth' in f && (f.innerWidth !== v.width || f.overflowX)) {
      problems.push(`${v.name} ${screen}: lays out at ${f.innerWidth} css px (document ${f.scrollWidth}), not ${v.width}`)
    }
  }
}
if (problems.length) {
  console.error(problems.join('\n'))
  process.exit(1)
}
console.error(`ok: every screen lays out at its width (${VIEWS.map((v) => v.width).join(', ')} css px)`)
