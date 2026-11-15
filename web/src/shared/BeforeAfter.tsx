import { AFP, ARDENT } from '../tour'

// The problem and what the desk does about it, in plain words, above every layout's demo: today by hand set against
// the desk, the two figures with their publishers, then the four steps. The figures are quoted from the sources
// tour.ts links; everything else is what the app does, which the rest of the page shows working.
export function BeforeAfter() {
  return (
    <section className="ba" aria-label="The problem and what this does">
      <div className="ba-cols">
        <div className="ba-col ba-before">
          <p className="ba-head">Today, by hand</p>
          <ul>
            <li>Someone types every bill in</li>
            <li>Checks each line against the order and the delivery</li>
            <li>Chases the vendor when something does not match</li>
            <li>A fake "we changed banks" email can slip through</li>
          </ul>
        </div>
        <div className="ba-col ba-after">
          <p className="ba-head">With ledger-desk</p>
          <ul>
            <li>AI reads the PDF or the phone photo</li>
            <li>Code checks every line against the order, the delivery and the paid bills</li>
            <li>The email to the vendor is drafted for you</li>
            <li>A bank change waits for a call to the number on file</li>
          </ul>
        </div>
      </div>
      <p className="ba-src">
        18.4% of bills have a problem (<a href={ARDENT.url} target="_blank" rel="noreferrer">{ARDENT.label}</a>) · 45% of organizations saw
        criminals pretending to be a vendor (<a href={AFP.url} target="_blank" rel="noreferrer">{AFP.label}</a>)
      </p>
      <p className="ba-how">How it works</p>
      <ol className="ba-steps" aria-label="How it works">
        <li>
          <b>1</b>
          <span className="ba-step">A bill arrives</span>
          <span className="ba-sub">a PDF or a phone photo</span>
        </li>
        <li>
          <b>2</b>
          <span className="ba-step">AI reads it</span>
          <span className="ba-sub">every line, with where it came from</span>
        </li>
        <li>
          <b>3</b>
          <span className="ba-step">Code checks it</span>
          <span className="ba-sub">the order, the delivery, the paid bills, the bank</span>
        </li>
        <li>
          <b>4</b>
          <span className="ba-step">You decide</span>
          <span className="ba-sub">one click, then it is booked</span>
        </li>
      </ol>
    </section>
  )
}
