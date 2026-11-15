// "How it works": the six steps a bill goes through (site.ts howSteps), shown five ways, each on real data. The
// engines are the sibling demo's; what they draw is this product's:
//   Field    - one mark per bill the eval read (a dot per PDF, a square per photo), each with its real outcome,
//              narrowing to the ones a person must look at (01, 08)
//   Player   - one recorded run stepped through the six steps (06, 09)
//   Story    - the steps as you scroll, a sticky panel showing each, on the bank-change run (05)
//   Pipeline - the whole workflow as one figure (04)
//   Line     - the six steps as boxes, a dot carrying a bill along a line under them (07)
// Colours come from the palette variables; every number from site-data.json through site.ts. Under reduced motion
// nothing moves on its own: the field shows its last frame, the player waits for a click, the dot does not travel.

import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties } from 'react'

import { amount, fieldModel, howSteps, money, runOf, SITE, walkOf, type Walk } from '../site.ts'
import { lookupInput, toolLabel } from '../system-map.ts'
import { useMotion } from '../live.ts'
import { markSizes } from './field.ts'

const HOW = howSteps()

/* ---------------------------------------------------------------- one step of one run */

function Typed({ text, ms, run }: { text: string; ms: number; run: boolean }) {
  const [n, setN] = useState(run ? 0 : text.length)
  useEffect(() => {
    if (!run) {
      const t = setTimeout(() => setN(text.length), 0)
      return () => clearTimeout(t)
    }
    let shown = 0
    const per = Math.max(1, Math.ceil(text.length / (ms / 16)))
    const t = setInterval(() => {
      shown = Math.min(text.length, shown + per)
      setN(shown)
      if (shown >= text.length) clearInterval(t)
    }, 16)
    return () => clearInterval(t)
  }, [text, ms, run])
  return (
    <>
      {text.slice(0, n)}
      {n < text.length && <span className="caret" />}
    </>
  )
}

const meter = (label: string, v: number, max: number) => (
  <div className="meter in" key={label}>
    <span className="mlab">{label}</span>
    <span className="mbar">
      <i style={{ width: `${Math.min(100, (100 * v) / max).toFixed(1)}%` }} />
    </span>
    <span className="mval">
      {v} of {max}
    </span>
  </div>
)

/** What one step of one recorded run looked like. `typing` animates the bill's name. */
export function StepView({ w, typing = false }: { w: Walk; typing?: boolean }) {
  switch (w.kind) {
    case 'bill':
      return (
        <>
          <p className="lbl">Real run · the bill</p>
          <p className="qtext">
            <Typed text={`${w.vendor} ${w.number}, ${amount(w.total)}`} ms={1300} run={typing} />
          </p>
          <p className="pfoot">A PDF or a phone photo goes in. Nobody types the bill in.</p>
        </>
      )
    case 'read':
      return (
        <>
          <p className="lbl in">What Claude read · each value with the line it came from</p>
          <div className="rows">
            <div className="rrow in ok">
              <span className="rk">PDF</span>
              <span className="rs">quoted lines found in the PDF</span>
              <span className="rsum">
                {w.ok} of {w.of}
              </span>
            </div>
            {w.missing > 0 && (
              <div className="rrow in bad">
                <span className="rk">PDF</span>
                <span className="rs">quoted lines not found</span>
                <span className="rsum">{w.missing}</span>
              </div>
            )}
            {w.notChecked > 0 && (
              <div className="rrow in">
                <span className="rk">Photo</span>
                <span className="rs">no text layer: checked by eye</span>
                <span className="rsum">{w.notChecked}</span>
              </div>
            )}
          </div>
          <p className="pfoot in">Code looks for every quoted line in the PDF's own text, so a misread value cannot slip through.</p>
        </>
      )
    case 'checks':
      return (
        <>
          <p className="lbl in">The checks, in code · {w.checks} of them</p>
          {w.flags.length ? (
            w.flags.map((f, i) => (
              <div key={f.code} className="in">
                <p className="pquote">
                  {f.words.charAt(0).toUpperCase() + f.words.slice(1)}
                  {f.amount ? ` (${amount(f.amount)})` : ''}
                </p>
                <span className="stamp bad" style={{ '--d': `${500 + i * 400}ms` } as CSSProperties}>
                  Flagged
                </span>
              </div>
            ))
          ) : (
            <div className="rows">
              <div className="rrow in ok">
                <span className="rk">ok</span>
                <span className="rs">Every check passed: the order, the delivery, the paid bills, the bank details, the arithmetic.</span>
              </div>
            </div>
          )}
        </>
      )
    case 'lookups':
      return (
        <>
          <p className="lbl in">Claude's lookups · read-only, {w.lookups.length} in this run</p>
          {w.lookups.length ? (
            <div className="rows">
              {w.lookups.map((l, i) => (
                <div className={`rrow in${l.ok ? '' : ' bad'}`} key={i}>
                  <span className="rk">{toolLabel(l.tool)}</span>
                  <span className="rs" title={lookupInput(l.input)}>
                    {lookupInput(l.input) || 'no input'}
                  </span>
                  <span className="rsum">{l.result}</span>
                </div>
              ))}
              {w.drafted && (
                <div className="rrow in">
                  <span className="rk">Draft email</span>
                  <span className="rs">to the vendor</span>
                  <span className="rsum">saved for a person, not sent</span>
                </div>
              )}
            </div>
          ) : (
            <p className="pquote in">No lookups: every check passed, so there was nothing to look into.</p>
          )}
          <p className="pfoot in">The agent can only read the books and save a draft. It cannot approve, book or pay.</p>
        </>
      )
    case 'decide':
      return (
        <>
          <p className="lbl in">The suggested next step · a person decides</p>
          <p className="pend in">{w.next}</p>
          <p className="pfoot in">
            Worked out by code from what the checks found. {w.controllerFrom} or more, and any bank change, need the controller; nothing is booked until a
            person approves.
          </p>
        </>
      )
    case 'cost':
      return (
        <>
          <p className="lbl in">This run · measured</p>
          <div className="meters">{meter('Lookups', w.lookups, w.maxLookups)}</div>
          <p className="pfoot in">
            {w.calls} model calls, {money(w.costUsd)} at API list prices, {w.seconds.toFixed(1)} s for the recorded run. The demo replays it, so a visit
            costs nothing.
          </p>
        </>
      )
  }
}

/** The explanation of one step, under a visual. */
export function Explain({ i }: { i: number | null }) {
  if (i === null) return null
  return (
    <div className="fexplain">
      <div className="h3">{HOW[i].title}</div>
      <p>{HOW[i].text}</p>
    </div>
  )
}

/* ---------------------------------------------------------------- the dot field */

const cssVar = (n: string) => getComputedStyle(document.documentElement).getPropertyValue('--' + n).trim()
const FIELD = fieldModel(SITE.field.cases)
// the run whose lookups the field shows at step 4: the overcharge, as in the system map's tour
const FIELD_RUN = walkOf(runOf('03'))

export function Field() {
  const f = FIELD
  const motion = useMotion()
  const box = useRef<HTMLDivElement>(null)
  const cv = useRef<HTMLCanvasElement>(null)
  const ctl = useRef<{ pick(i: number): void; toggle(): void } | null>(null)
  const [stage, setStage] = useState(motion ? 0 : 5)
  const [playing, setPlaying] = useState(motion)
  const [open, setOpen] = useState<number | null>(null)

  useEffect(() => {
    const root = box.current!, canvas = cv.current!, ctx = canvas.getContext('2d')
    if (!ctx) return
    const light = document.body.classList.contains('light')
    const C = { a1: cssVar('a1'), a3: cssVar('a3'), dim: cssVar('line'), tx: cssVar('tx'), mu: cssVar('mu'), bg: cssVar('bg'), ok: light ? '#1f8a4c' : '#3fbf7f', bad: light ? '#b42b2b' : '#ef7a6a', fb: cssVar('fb') }
    const N = f.n
    const look = FIELD_RUN[3].kind === 'lookups' ? FIELD_RUN[3] : null
    const lookLines = look ? [...look.lookups.map((l) => `${toolLabel(l.tool)}: ${l.result}`), ...(look.drafted ? ['Draft email: saved for a person, not sent'] : [])] : []

    let W = 0, H = 0, pitch = 0, pos: [number, number][] = [], card = { x: 0, y: 0, w: 0, h: 0 }
    function layout() {
      W = root.clientWidth
      const narrow = W < 560, pad = 12
      // few marks: a generous grid, capped so a mark never grows past a readable size
      pitch = Math.min(44, Math.max(8, Math.floor(Math.sqrt(((W - 2 * pad) * (narrow ? 200 : 150)) / N))))
      const cols = Math.max(1, Math.min(N, Math.floor((narrow ? W - 2 * pad : W * 0.46) / pitch))), rows = Math.ceil(N / cols)
      H = Math.max(rows * pitch + 2 * pad + (narrow ? 220 : 0), 260)
      const dpr = window.devicePixelRatio || 1
      canvas.width = Math.round(W * dpr)
      canvas.height = Math.round(H * dpr)
      canvas.style.width = W + 'px'
      canvas.style.height = H + 'px'
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0)
      const gridW = cols * pitch
      const ox = narrow ? (W - gridW) / 2 + pitch / 2 : 16 + pitch / 2, oy = pad + pitch / 2
      pos = Array.from({ length: N }, (_, i) => [ox + (i % cols) * pitch, oy + Math.floor(i / cols) * pitch])
      const cw = narrow ? W - 24 : Math.min(W - gridW - 48, 470), ch = narrow ? 196 : Math.min(H - 24, 220)
      card = { x: narrow ? 12 : W - cw - 16, y: narrow ? H - ch - 12 : (H - ch) / 2, w: cw, h: ch }
    }
    const ease = (x: number) => (x < 0 ? 0 : x > 1 ? 1 : x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2)
    const rrect = (x: number, y: number, w: number, h: number, r: number) => {
      ctx!.beginPath()
      // older browsers have no roundRect: square corners there
      if (typeof (ctx as { roundRect?: unknown }).roundRect === 'function') ctx!.roundRect(x, y, w, h, r)
      else ctx!.rect(x, y, w, h)
    }
    const fit = (s: string, w: number) => {
      if (ctx!.measureText(s).width <= w) return s
      while (s.length > 1 && ctx!.measureText(s + '…').width > w) s = s.slice(0, -1)
      return s + '…'
    }

    function draw(s: number, p: number) {
      const g = ctx!
      g.clearRect(0, 0, W, H)
      const size = markSizes(pitch)
      for (let i = 0; i < N; i++) {
        const m = f.marks[i]
        let col = C.dim, a = 1, grow = 0
        if (s === 1) {
          const lit = p > i / N
          col = lit ? C.a1 : C.dim
          grow = lit && p - i / N < 0.08 ? 1 : 0
        } else if (s >= 2) {
          col = m.flagged ? C.a3 : C.ok
          a = m.flagged ? 1 : s >= 3 && s < 5 ? 0.35 : 0.75
          grow = s === 2 && m.flagged ? ease(p * 2) : 0
        }
        g.globalAlpha = s === 0 ? 0.55 : a
        g.fillStyle = col
        const [x, y] = pos[i]
        if (m.photo) {
          const d = (s === 0 ? size.dot * 1.7 : size.square) * (1 + 0.15 * grow)
          rrect(x - d / 2, y - d / 2, d, d, 2)
          g.fill()
        } else {
          const r = s === 0 ? size.dot : size.lit + (size.pulse - size.lit) * grow
          g.beginPath()
          g.arc(x, y, r, 0, 7)
          g.fill()
        }
        // the one bill that did not end exactly as its answer key says, ringed at the end
        if (s === 5 && !m.exact) {
          g.globalAlpha = 1
          g.strokeStyle = C.bad
          g.lineWidth = 2
          g.beginPath()
          g.arc(x, y, size.pulse + 3, 0, 7)
          g.stroke()
        }
      }
      g.globalAlpha = 1
      if (s === 0) {
        g.font = `500 14px ${C.fb}`
        const k = ease(p * 2.2), txt = fit(f.captions[0], card.w - 30), bw = g.measureText(txt).width + 30, bx = card.x + (card.w - bw) / 2, by = card.y + card.h / 2 - 20 + (1 - k) * 8
        g.globalAlpha = k
        g.fillStyle = C.bg
        rrect(bx, by, bw, 40, 20)
        g.fill()
        g.strokeStyle = C.a1
        g.lineWidth = 1.5
        g.stroke()
        g.fillStyle = C.tx
        g.textBaseline = 'middle'
        g.fillText(txt, bx + 15, by + 20)
        g.globalAlpha = 1
      }
      if (s >= 3) {
        const c = card, a = s === 3 ? ease(p * 2.5) : 1
        g.globalAlpha = a
        g.fillStyle = C.bg
        rrect(c.x, c.y, c.w, c.h, 12)
        g.fill()
        g.strokeStyle = s === 5 ? C.ok : C.mu
        g.lineWidth = s === 5 ? 2 : 1
        g.stroke()
        g.textBaseline = 'top'
        g.fillStyle = C.mu
        g.font = "500 10.5px 'JetBrains Mono', monospace"
        g.fillText(['', '', '', "CLAUDE'S LOOKUPS · ONE RECORDED RUN", 'A PERSON DECIDES', 'MEASURED'][s], c.x + 14, c.y + 12)
        const top = c.y + 34, inner = c.w - 28
        if (s === 3) {
          g.font = `400 ${c.w < 300 ? 11.5 : 12.5}px ${C.fb}`
          const shown = Math.ceil(lookLines.length * ease(p * 1.4))
          lookLines.slice(0, shown).forEach((ln, k) => {
            g.fillStyle = k === lookLines.length - 1 && look?.drafted ? C.mu : C.tx
            g.fillText(fit(ln, inner), c.x + 14, top + k * 22)
          })
        }
        if (s === 4) {
          const rows: [string, string][] = [
            [`${f.clean} ready: one click each`, C.ok],
            [`${f.flagged} need a look: each with a suggested next step`, C.a3],
          ]
          rows.forEach(([t, col], k) => {
            g.fillStyle = col
            g.beginPath()
            g.arc(c.x + 20, top + 10 + k * 34, 5, 0, 7)
            g.fill()
            g.fillStyle = C.tx
            g.font = `500 ${c.w < 300 ? 12.5 : 13.5}px ${C.fb}`
            g.fillText(fit(t, inner - 22), c.x + 34, top + 3 + k * 34)
          })
        }
        if (s === 5) {
          const rows: [string, number][] = [
            ['Ended as the answer key says', f.exact],
            ['Booked nothing without a person', f.safe],
          ]
          const k = ease(p * 1.5), lw = Math.min(170, inner * 0.5)
          rows.forEach(([label, v], j) => {
            const y = top + 6 + j * 40
            g.font = `500 12.5px ${C.fb}`
            g.fillStyle = C.tx
            g.fillText(fit(label, lw - 6), c.x + 14, y)
            g.fillStyle = C.mu
            g.font = "400 11px 'JetBrains Mono', monospace"
            g.fillText(`${v} of ${f.n}`, c.x + 14, y + 16)
            const bx = c.x + 14 + lw, bw = inner - lw
            g.fillStyle = C.dim
            rrect(bx, y + 4, bw, 8, 4)
            g.fill()
            g.fillStyle = C.a1
            rrect(bx, y + 4, Math.max(8, (bw * v * k) / f.n), 8, 4)
            g.fill()
          })
        }
        g.globalAlpha = 1
      }
    }

    const DUR = [2200, 3000, 2800, 3200, 2800, 3000]
    let s = motion ? 0 : 5, t0 = performance.now(), play = motion, visible = false, raf = 0, dead = false
    const set = (k: number) => {
      s = k
      t0 = performance.now()
      setStage(k)
    }
    function frame(now: number) {
      raf = 0
      if (dead || !play || !visible) return
      let p = (now - t0) / DUR[s]
      if (p >= 1) {
        set((s + 1) % 6)
        p = 0
      }
      draw(s, p)
      raf = requestAnimationFrame(frame)
    }
    const run = () => {
      if (!raf && play && visible) raf = requestAnimationFrame(frame)
    }
    ctl.current = {
      pick(i) {
        play = false
        setPlaying(false)
        set(i)
        draw(i, 1)
      },
      toggle() {
        play = !play
        setPlaying(play)
        if (play) {
          t0 = performance.now()
          run()
        } else draw(s, 1)
      },
    }
    layout()
    draw(s, motion ? 0 : 1)
    const ro = new ResizeObserver(() => {
      if (root.clientWidth && root.clientWidth !== W) {
        layout()
        draw(s, play ? 0 : 1)
      }
    })
    ro.observe(root)
    // plays only while on screen
    const io = new IntersectionObserver((es) => es.forEach((en) => {
      visible = en.isIntersecting
      if (visible) {
        t0 = performance.now()
        run()
      }
    }), { threshold: 0.25 })
    io.observe(root)
    // web fonts can land after the first frame: draw again once they have
    document.fonts?.ready.then(() => !dead && draw(s, 1))
    return () => {
      dead = true
      if (raf) cancelAnimationFrame(raf)
      ro.disconnect()
      io.disconnect()
    }
  }, [motion, f])

  return (
    <>
      <div className="funnel" ref={box}>
        <canvas
          ref={cv}
          role="img"
          aria-label={`Animation of the eval: ${f.n} bills (${f.n - f.photos} PDFs, ${f.photos} photos) are read, ${f.flagged} are flagged by the checks and ${f.clean} pass, the flagged ones are looked into and wait for a person, and ${f.exact} of ${f.n} ended exactly as their answer key says.`}
        />
        <div className="ftop">
          <p className="fcap">{f.captions[stage]}</p>
          {motion && (
            <button type="button" className="fplay" onClick={() => ctl.current?.toggle()}>
              {playing ? 'Pause' : 'Play'}
            </button>
          )}
        </div>
        <div className="fsteps">
          {HOW.map((h, i) => (
            <button
              type="button"
              key={h.title}
              className={`fstep${i === stage ? ' on' : ''}${i === open ? ' open' : ''}`}
              aria-pressed={i === open}
              onClick={() => {
                ctl.current?.pick(i)
                setOpen(open === i ? null : i)
              }}
            >
              {h.title}
            </button>
          ))}
        </div>
      </div>
      {!motion && (
        <ol className="flist">
          {f.captions.map((c, i) => (
            <li key={i}>
              <b>{HOW[i].title}.</b> {c}.
            </li>
          ))}
        </ol>
      )}
      <Explain i={open} />
    </>
  )
}

/* ---------------------------------------------------------------- the step-through player */

const PLAYER_RUNS: [string, string][] = [
  ['03', 'An overcharge'],
  ['08', 'A bank change'],
  ['09', 'A clean bill'],
]
const PLAYER_MS = [2600, 3200, 3200, 4200, 3600, 3200]

export function Player({ explain = true }: { explain?: boolean }) {
  const motion = useMotion()
  const [runKey, setRunKey] = useState(PLAYER_RUNS[0][0])
  const [k, setK] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [minH, setMinH] = useState(0)
  const root = useRef<HTMLDivElement>(null)
  const measureBox = useRef<HTMLDivElement>(null)
  const played = useRef(false)
  const steps = walkOf(runOf(runKey))

  // advance while playing; stop at the last step
  useEffect(() => {
    if (!playing) return
    const t = setTimeout(() => {
      if (k >= 5) setPlaying(false)
      else setK((x) => x + 1)
    }, k >= 5 ? 0 : PLAYER_MS[k])
    return () => clearTimeout(t)
  }, [playing, k])

  // plays once, the first time it scrolls into view; under reduced motion it waits for a click
  useEffect(() => {
    if (!motion || !root.current) return
    const io = new IntersectionObserver((es) => es.forEach((e) => {
      if (e.isIntersecting && !played.current) {
        played.current = true
        io.disconnect()
        setK(0)
        setPlaying(true)
      }
    }), { threshold: 0.45 })
    io.observe(root.current)
    return () => io.disconnect()
  }, [motion])

  // the stage keeps its tallest step's height, so the page does not jump while it plays
  useLayoutEffect(() => {
    const m = measureBox.current
    if (!m) return
    const measure = () => setMinH(Math.min(560, Math.max(...[...m.children].map((c) => (c as HTMLElement).offsetHeight))))
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(m)
    document.fonts?.ready.then(measure)
    return () => ro.disconnect()
  }, [runKey])

  const go = (i: number) => {
    setPlaying(false)
    setK(i)
  }
  return (
    <>
      <div className="player" ref={root}>
        <div className="prail">
          <i className="pprog" style={{ width: `calc((100% - 24px) * ${k} / 6)` }} />
          {HOW.map((h, i) => (
            <button type="button" key={h.title} className={`pstep${i === k ? ' on' : ''}${i < k ? ' past' : ''}`} aria-current={i === k ? 'step' : undefined} onClick={() => go(i)}>
              <span className="pn">{i + 1}</span>
              <span className="pt">{h.title}</span>
            </button>
          ))}
        </div>
        <div className="pstage-wrap">
          <div className="pstage" aria-live="polite" style={{ minHeight: minH || undefined }} key={`${runKey}-${k}`}>
            <StepView w={steps[k]} typing={playing && motion} />
          </div>
          <div className="pstage pmeasure" ref={measureBox} aria-hidden="true">
            {steps.map((w, i) => (
              <div key={i}>
                <StepView w={w} />
              </div>
            ))}
          </div>
        </div>
        <div className="pctl">
          <div className="ptogs">
            {PLAYER_RUNS.map(([key, label]) => (
              <button
                type="button"
                key={key}
                className="ptog"
                aria-pressed={key === runKey}
                onClick={() => {
                  setRunKey(key)
                  setK(0)
                  setPlaying(motion)
                }}
              >
                {label}
              </button>
            ))}
          </div>
          <button
            type="button"
            className="pbtn"
            onClick={() => {
              if (playing) return setPlaying(false)
              if (k >= 5) setK(0)
              setPlaying(true)
            }}
          >
            {playing ? 'Pause' : k >= 5 ? 'Play again' : 'Play'}
          </button>
        </div>
      </div>
      {explain && <Explain i={k} />}
    </>
  )
}

/* ---------------------------------------------------------------- the scroll story */

export function Story() {
  // the bank-change run: one lookup, and the controls a person is held to
  const steps = walkOf(runOf('08'))
  const [cur, setCur] = useState(0)
  const list = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const els = [...(list.current?.querySelectorAll<HTMLElement>('.st') ?? [])]
    const io = new IntersectionObserver((es) => es.forEach((x) => x.isIntersecting && setCur(Number((x.target as HTMLElement).dataset.st))), { rootMargin: '-45% 0px -45% 0px' })
    els.forEach((e) => io.observe(e))
    return () => io.disconnect()
  }, [])
  return (
    <div className="story">
      <div className="sticky">
        <div className="svis player-like" key={cur}>
          <StepView w={steps[cur]} />
        </div>
      </div>
      <div className="steps" ref={list}>
        {HOW.map((h, i) => (
          <div className={`st${i === cur ? ' on' : ''}`} data-st={i} key={h.title}>
            <span className="n">0{i + 1}</span>
            <div className="h3">{h.title}</div>
            <p>{h.text}</p>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ---------------------------------------------------------------- the pipeline figure */

export function Pipeline() {
  const p = SITE.policies
  const ctrl = '$' + p.controller_from.toLocaleString('en-US')
  const nodes = ['A bill · PDF or photo', `${SITE.model.name} reads it · fields and source lines`, `${SITE.checks} checks · code`, `Claude looks into a problem · read-only, at most ${p.max_lookups} lookups`, 'The next step · code', `A person decides · ${ctrl} or more: the controller`, 'Booked, or held, or rejected']
  return (
    <div className="fig">
      <div className="cap">Fig 1 · the bill desk</div>
      <svg
        viewBox="0 0 1100 320"
        role="img"
        aria-label={`The workflow: a bill is read by ${SITE.model.name}, ${SITE.checks} checks in code flag a problem or pass it, a flagged bill gets read-only lookups and a suggested next step, a person decides, and an approved bill is signed and booked.`}
      >
        <defs>
          <marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
            <path d="M0,0 L10,5 L0,10 z" fill="var(--acc)" />
          </marker>
          <linearGradient id="gw" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="1100" y2="0">
            <stop offset="0" stopColor="var(--a1)" />
            <stop offset=".5" stopColor="var(--a2)" />
            <stop offset="1" stopColor="var(--a3)" />
          </linearGradient>
        </defs>
        <g fill="none" stroke="url(#gw)" strokeWidth="2">
          <path d="M140 210 L170 210" markerEnd="url(#ar)" />
          <path d="M340 210 L370 210" markerEnd="url(#ar)" />
          <path d="M480 180 C480 140 560 140 560 112" markerEnd="url(#ar)" />
          <path d="M650 70 L700 70" markerEnd="url(#ar)" />
          <path d="M775 100 L775 178" markerEnd="url(#ar)" />
          <path d="M540 210 L688 210" markerEnd="url(#ar)" strokeDasharray="5 5" />
          <path d="M860 198 C885 198 885 124 903 124" markerEnd="url(#ar)" />
          <path d="M860 222 C885 222 885 274 903 274" markerEnd="url(#ar)" strokeDasharray="5 5" />
        </g>
        <g fontSize="13" fill="var(--tx)">
          <rect x="20" y="180" width="120" height="60" rx="12" fill="var(--card2)" stroke="var(--line)" />
          <text x="80" y="207" textAnchor="middle">A BILL</text>
          <text x="80" y="225" textAnchor="middle" fill="var(--mu)" fontSize="11">PDF or photo</text>
          <rect x="170" y="180" width="170" height="60" rx="12" fill="var(--card2)" stroke="var(--line)" />
          <text x="255" y="207" textAnchor="middle">{SITE.model.name.toUpperCase()}</text>
          <text x="255" y="225" textAnchor="middle" fill="var(--mu)" fontSize="11">reads it, line by line</text>
          <rect x="370" y="180" width="170" height="60" rx="12" fill="none" stroke="var(--acc)" strokeWidth="2" />
          <text x="455" y="207" textAnchor="middle" fill="var(--acc)">{SITE.checks} CHECKS</text>
          <text x="455" y="225" textAnchor="middle" fill="var(--mu)" fontSize="11">code, after the model</text>
          <rect x="470" y="30" width="180" height="80" rx="12" fill="var(--card2)" stroke="var(--line)" />
          <text x="560" y="62" textAnchor="middle">CLAUDE LOOKS INTO IT</text>
          <text x="560" y="81" textAnchor="middle" fill="var(--mu)" fontSize="11">read-only, at most {p.max_lookups} lookups</text>
          <text x="560" y="97" textAnchor="middle" fill="var(--mu)" fontSize="11">a draft email, never sent</text>
          <rect x="700" y="40" width="150" height="60" rx="12" fill="none" stroke="var(--acc)" strokeWidth="2" />
          <text x="775" y="67" textAnchor="middle" fill="var(--acc)">NEXT STEP</text>
          <text x="775" y="85" textAnchor="middle" fill="var(--mu)" fontSize="11">code: hold, reject, approve</text>
          <rect x="690" y="180" width="170" height="60" rx="12" fill="var(--card2)" stroke="var(--line)" />
          <text x="775" y="207" textAnchor="middle">A PERSON</text>
          <text x="775" y="225" textAnchor="middle" fill="var(--mu)" fontSize="11">{ctrl} or more: the controller</text>
          <rect x="905" y="100" width="175" height="48" rx="24" fill="var(--card)" stroke="var(--line)" />
          <text x="992" y="129" textAnchor="middle">BOOKED, SIGNED</text>
          <rect x="905" y="250" width="175" height="48" rx="24" fill="var(--card)" stroke="var(--line)" />
          <text x="992" y="279" textAnchor="middle" fill="var(--mu)">HELD OR REJECTED</text>
          <text x="600" y="203" textAnchor="middle" fill="var(--mu)" fontSize="11">clean</text>
          <text x="455" y="150" textAnchor="middle" fill="var(--mu)" fontSize="11">a problem</text>
          <g fill="var(--acc)" fontSize="11">
            <text x="20" y="170">1</text>
            <text x="170" y="170">2</text>
            <text x="370" y="170">3</text>
            <text x="470" y="22">4</text>
            <text x="700" y="32">5</text>
            <text x="690" y="170">6</text>
          </g>
        </g>
      </svg>
      <div className="vpipe">
        {nodes.map((t, i) => (
          <div className="nd" key={t}>
            <b>{i + 1}</b>
            {t}
          </div>
        ))}
      </div>
      <div className="callouts">
        {HOW.map((h, i) => (
          <div className="co" key={h.title}>
            <b>
              {i + 1} · {h.title.toUpperCase()}
            </b>
            <span>{h.text}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ---------------------------------------------------------------- the moving line (one-column) */

export function Line() {
  const motion = useMotion()
  const [k, setK] = useState(0)
  const [running, setRunning] = useState(motion)
  const [open, setOpen] = useState<number | null>(null)
  const line = useRef<HTMLDivElement>(null)
  const [geo, setGeo] = useState<number[]>([])
  const stations = HOW.map((h) => h.sub)

  useLayoutEffect(() => {
    const el = line.current
    if (!el) return
    const measure = () => setGeo([...el.querySelectorAll<HTMLElement>('.station')].map((s) => s.offsetLeft + s.offsetWidth / 2))
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  // the dot moves only while the diagram is on screen
  useEffect(() => {
    if (!motion || !running || !line.current) return
    let t: ReturnType<typeof setInterval> | undefined
    const io = new IntersectionObserver((es) => es.forEach((e) => {
      clearInterval(t)
      if (e.isIntersecting) t = setInterval(() => setK((x) => (x + 1) % 6), 1400)
    }), { threshold: 0.2 })
    io.observe(line.current)
    return () => {
      clearInterval(t)
      io.disconnect()
    }
  }, [motion, running])

  const x = (i: number) => geo[i] ?? 0
  return (
    <>
      <div className="howbar">
        <p className="sub">Click a step.</p>
        {motion && (
          <button type="button" className="playbtn" onClick={() => setRunning(!running)}>
            {running ? 'Pause' : 'Play the flow'}
          </button>
        )}
      </div>
      <div className="flow">
        {HOW.map((h, i) => (
          <button
            type="button"
            className={`node${i === k ? ' lit' : ''}`}
            aria-expanded={open === i}
            key={h.title}
            onClick={() => {
              setRunning(false)
              setK(i)
              setOpen(open === i ? null : i)
            }}
          >
            <b>{h.title}</b>
            <span>{h.sub}</span>
          </button>
        ))}
      </div>
      <div className="line" ref={line} aria-hidden="true">
        <i className="track" style={{ left: x(0), width: x(5) - x(0) }} />
        <i className="fillbar" style={{ left: x(0), width: x(k) - x(0) }} />
        {stations.map((s, i) => (
          <div key={s} className={`station${i === k ? ' on' : ''}${i < k ? ' past' : ''}`}>
            {s}
          </div>
        ))}
        {motion && geo.length > 0 && <i className={`dot${k === 5 ? ' ok' : ''}`} style={{ transform: `translate(${x(k)}px, 0)` }} />}
      </div>
      <Explain i={open} />
    </>
  )
}
