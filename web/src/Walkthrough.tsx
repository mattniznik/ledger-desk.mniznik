import { TOUR } from './tour'

type Props = { step: number; note: string; onStep: (n: number) => void; onExit: () => void; onRestart: () => void }

// The bar above the real screens while the walkthrough runs: the struggle first, then what the AI does
// about it, then what code and people do. Desk.tsx opens the bill or the tab each step names.
export function Walkthrough({ step, note, onStep, onExit, onRestart }: Props) {
  const s = TOUR[step]
  const last = step === TOUR.length - 1
  return (
    <aside className="tour" aria-label="Walkthrough">
      <p className="tour-count">Walkthrough · Step {step + 1} of {TOUR.length}</p>
      <h2>{s.title}</h2>
      <p>
        <strong>The struggle:</strong> {s.struggle}
        {s.source && <> <a href={s.source.url} target="_blank" rel="noreferrer">Source: {s.source.label}</a></>}
      </p>
      <p><strong>What the AI does:</strong> {s.ai}</p>
      <p><strong>What code and people do:</strong> {s.app}</p>
      {note && <p className="fine" role="status">{note}</p>}
      <div className="buttons">
        <button disabled={step === 0} data-tour="step" data-step={step} onClick={() => onStep(step - 1)}>Back</button>
        {last ? <button className="primary" data-tour="finish" onClick={onExit}>Finish</button> : <button className="primary" data-tour="step" data-step={step + 2} onClick={() => onStep(step + 1)}>Next</button>}
        {!last && <button className="link" data-tour="exit" onClick={onExit}>Exit the walkthrough</button>}
        <button className="link" data-tour="restart" onClick={onRestart}>Start over with fresh bills</button>
      </div>
    </aside>
  )
}
