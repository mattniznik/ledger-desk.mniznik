import { type Run, modeLabel } from './api'

const n = (v: number) => v.toLocaleString('en-US')

// What one run cost: model calls, every kind of token (cache writes and reads included, since
// most of the prompt is cached), the cost at API list prices, and how long the run took.
export function MetricsFooter({ run }: { run: Pick<Run, 'mode' | 'model' | 'metrics' | 'seconds'> }) {
  const m = run.metrics
  return (
    <footer className="metrics">
      {m && m.cost_usd === null && m.input_tokens + m.output_tokens === 0 ? (
        <span>{m.model_calls} model calls, scripted: no model, no cost</span>
      ) : m ? (
        <span>
          {m.model_calls} model calls · tokens {n(m.input_tokens)} in + {n(m.cache_write_tokens)} cache write + {n(m.cache_read_tokens)} cache read, {n(m.output_tokens)} out
          {m.cost_usd !== null && <> · ${m.cost_usd.toFixed(4)} at API list prices</>}
          {run.seconds !== null && run.seconds !== undefined && <> · the recorded run took {run.seconds} s</>}
        </span>
      ) : null}
      <span className="source">{modeLabel(run)}</span>
    </footer>
  )
}
