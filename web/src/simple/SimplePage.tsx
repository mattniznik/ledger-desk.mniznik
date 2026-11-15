// The three one-column layouts (07, 08, 09): one plain column in three looks. The bill desk, the system map, How it
// works (a moving line, a dot field or a step-through player), the measured runs, how it was built and the footer.
// Every number comes from site-data.json (site.ts).

import { useEffect } from 'react'
import { BeforeAfter } from '../shared/BeforeAfter.tsx'

import './simple.css'
import { Desk } from '../Desk.tsx'
import { Studio } from '../studio/Studio.tsx'
import type { Cfg, Choice } from '../studio/choice.ts'
import { Built } from '../shared/Built.tsx'
import { Field, Line, Player } from '../shared/How.tsx'
import { SystemMapSection } from '../shared/SystemMap.tsx'
import { COMPANY, COST_RANGE, COST_TOTAL, DISCLAIMER, LEDE, SITE, TEST_FILES, TESTS } from '../shared/data.ts'
import { billTitle, flagWords, howSub, money, toolCount } from '../site.ts'

const rec = SITE.recorded

export function SimplePage({ cfg, choice }: { cfg: Cfg; choice: Choice }) {
  useEffect(() => document.documentElement.classList.remove('boot'), [])
  const d = cfg.simple ?? 1
  return (
    <>
      <main className="smain">
        <p className="s-eyebrow">{COMPANY}</p>
        <h1>
          Supplier bills, {d === 2 ? <span className="grad">checked before they are paid</span> : d === 3 ? <em>checked before they are paid</em> : 'checked before they are paid'}
        </h1>
        <p className="lede">{LEDE}</p>

        <BeforeAfter />

        <Desk />

        <SystemMapSection />

        <h2 id="how">How it works</h2>
        {d === 1 && <Line />}
        {d === 2 && (
          <>
            <p className="sub">{howSub('field')}</p>
            <Field />
          </>
        )}
        {d === 3 && (
          <>
            <p className="sub">{howSub('player')}</p>
            <Player />
          </>
        )}

        <h2 id="results">How well it works</h2>
        <p className="sub">
          {rec.n} real runs of {SITE.model.name}, with the tokens and time they reported; at API list prices, {COST_TOTAL} for all of them,
          {COST_RANGE} each.{' '}
          {rec.matched} of {rec.n} bills ended exactly as their answer key says. {TESTS} tests in {TEST_FILES} files passed when this page was built.
        </p>
        <div className="stable-wrap">
          <table className="stable">
            <thead>
              <tr>
                <th>Recorded bill</th>
                <th className="n">Model calls</th>
                <th className="n">Lookups</th>
                <th className="n">Seconds</th>
                <th className="n">Cost</th>
              </tr>
            </thead>
            <tbody>
              {rec.runs.map((r) => (
                <tr key={r.sample}>
                  <td>
                    {billTitle(r)}
                    {r.flags.map((f) => (
                      <span className="tag" key={f.code}>
                        {flagWords(f.code)}
                      </span>
                    ))}
                  </td>
                  <td className="n">{r.calls}</td>
                  <td className="n">{toolCount(r)}</td>
                  <td className="n">{r.seconds.toFixed(1)}</td>
                  <td className="n">{money(r.cost_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="note">Every eval run, with each miss, is under How it works in the desk.</p>

        <Built inMain />

        <footer className="sfoot">{DISCLAIMER}</footer>
      </main>
      <Studio choice={choice} placement="fab" />
    </>
  )
}
