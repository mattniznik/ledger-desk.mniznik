import type { Client } from './api'
import { EvalsPage } from './EvalsPage'
import { AFP, ARDENT, FBI } from './tour'
import { controllerFrom, modelRun, SITE } from './site'

// Who the app is for and what it does for them, in their words; then the engineering evidence (the
// evals) for anyone who wants to know how well it does it. The approval rules quoted here are the
// ones src/ledger_desk/authority.py and rules.py enforce.
export function HowItWorks({ client }: { client: Client }) {
  return (
    <>
      <section className="about">
        <h2>How it works</h2>
        <h3>Who it is for</h3>
        <p>
          A small business that buys from suppliers on account, like this roastery. Today a bookkeeper types each
          supplier bill into QuickBooks, checks it against the purchase order and the delivery slip, and the owner or controller signs
          off before it is paid. Overcharges, bills sent twice and fake "we changed banks" requests get through when that checking is
          rushed.
        </p>
        <h3>The problem it solves</h3>
        <p>Typing bills in takes time. The bills that do not match need someone to dig, decide and chase the vendor, and fraud gets through when that checking is rushed:</p>
        <ul>
          <li>
            Across the accounts-payable teams surveyed, 18.4% of bills have a problem, the average bill takes 8.2 days and $9.84 to
            process, and staff spend 21.9% of their time dealing with suppliers, in no small part because of problem bills.{' '}
            <a href={ARDENT.url} target="_blank" rel="noreferrer">{ARDENT.label}</a>
          </li>
          <li>
            In 2024, 79% of the organizations surveyed saw attempted or actual payments fraud and 45% reported criminals pretending to be a
            vendor; only 22% got back 75% or more of what was lost. <a href={AFP.url} target="_blank" rel="noreferrer">{AFP.label}</a>
          </li>
          <li>
            The FBI received 21,442 complaints of business email compromise in 2024, close to $2.8 billion lost.{' '}
            <a href={FBI.url} target="_blank" rel="noreferrer">{FBI.label}</a>
          </li>
        </ul>
        <p>
          So the app spends its effort on the problem bills: each one arrives with what is wrong, the evidence, and a suggested next step a
          finance team would take, and a person decides.
        </p>
        <h3>What it does for them</h3>
        <ul>
          <li>Reads each bill, PDF or phone photo: vendor, lines, totals, bank details.</li>
          <li>
            Checks it against the purchase order, what was actually delivered, past bills and the vendor's bank details on file, so
            overcharges, repeat bills and bank-change fraud are caught before money leaves.
          </li>
          <li>Clean bills wait for one click. Problem bills say what is wrong in plain words and come with the next step: hold for a corrected bill, approve against a credit the vendor already sent, reject a copy already paid, or hold a bank change until the vendor confirms it by phone. The email to the vendor is drafted.</li>
          <li>Approved bills are booked in the company's books and, when QuickBooks is connected, added there with the account and the due date, ready to pay.</li>
        </ul>
        <h3>Where the AI helps, and where it does not</h3>
        <p>Claude does the reading, the digging and the writing. Plain code does every check and every sum. People make every decision about money.</p>
        <div className="table-wrap">
          <table className="ai-roles">
            <caption>Where the AI helps</caption>
            <thead>
              <tr><th scope="col">The problem</th><th scope="col">What the AI does</th><th scope="col">What code does</th><th scope="col">What people do</th></tr>
            </thead>
            <tbody>
            <tr><th scope="row">Typing bills in</th><td>Reads each PDF or phone photo into vendor, lines, totals and bank details, with no template per vendor, and quotes where each value came from</td><td>Checks each quote is really in the PDF</td><td>Check a phone photo by eye</td></tr>
            <tr><th scope="row">Bills that do not match the order or the delivery</th><td>Looks up the purchase order, the delivery and the vendor, explains what is wrong, and drafts the email to the vendor</td><td>Finds the mismatch and works out the amount, matches any credit memo waiting for it, and suggests the next step</td><td>Decide, and send the email</td></tr>
            <tr><th scope="row">Bills paid twice</th><td>Finds the earlier copy among the paid bills and drafts a note to the vendor</td><td>Matches the bill number against the paid bills; suggests rejecting it</td><td>Reject it</td></tr>
            <tr><th scope="row">Fake bank-change requests</th><td>Explains what changed and drafts an email saying the change will be confirmed by phone</td><td>Flags the new account; only the controller may approve, after the phone check</td><td>Call the vendor on the number already on file</td></tr>
            <tr><th scope="row">Coding a bill with no purchase order</th><td>Suggests the account, with its reason</td><td>Accepts it only if it is in the chart of accounts and fits the vendor</td><td>Approve, which signs off the account too</td></tr>
            <tr><th scope="row">Bills written to fool an AI</th><td>Is told to treat bill text as data, and has no tool that could approve or pay, so it cannot act on it even if fooled</td><td>Flags instruction-like wording with a phrase check, which ordinary wording can also trip</td><td>Read it; if it is aimed at an AI, confirm the bill with the vendor</td></tr>
            <tr><th scope="row">Showing an auditor what happened</th><td>Each AI step is logged with the model calls and tokens it used; each bill shows its time and cost</td><td>Keeps a hash-chained audit trail of every step</td><td>Press Verify</td></tr>
            </tbody>
          </table>
        </div>
        <Measured />
        <h3>What stays with people</h3>
        <ul>
          <li>Nothing is booked or paid until a person approves it.</li>
          <li>Bills of {controllerFrom()} or more, and equipment its purchase order puts on the asset account, need the controller.</li>
          <li>A change of bank account needs the controller and a phone call to the number already on file.</li>
          <li>Every step is in the audit trail, and the trail shows if anyone edits it afterwards.</li>
        </ul>
        <h3>Under the hood</h3>
        <p>
          Claude reads each bill and writes the explanations. Plain code does every check and every sum. A LangGraph workflow pauses
          for the approval, and approved bills post to the company's books (a mock ERP) and, when the connector is switched on, to a QuickBooks Online sandbox company.
          The evals below measure how well the reading and the checks do.
        </p>
        <p>
          It runs on Microsoft Azure: the app API and the mock ERP on Azure Container Apps, which scale to zero when nobody visits; the
          database on Azure Database for PostgreSQL; the secrets in Azure Key Vault; and this page on Azure Static Web Apps. The
          infrastructure is Terraform.
        </p>
      </section>
      <EvalsPage client={client} />
    </>
  )
}

// How well it does it, from the results files (site-data.json); nothing typed in
function Measured() {
  const std = modelRun('standard')
  const hard = modelRun('hard')
  if (!std) return null
  const unsafe = std.cases - std.safe
  return (
    <p>
      How well it does it, measured in one eval run of {std.cases} bills on {SITE.model.name}: {std.fields_correct} of {std.fields} fields
      read correctly ({std.pdf_fields} from PDFs, {std.photo_fields} from photos), {std.account_top1} of {std.account_graded} accounts
      suggested correctly, {std.end_result} of {std.cases} bills ended in the right state, and{' '}
      {unsafe === 0 ? 'none' : `${unsafe} of ${std.cases}`} reached the books without approval.
      {hard && <> On a harder set of {hard.cases} (blurred, skewed and creased photos, a two-page bill), {hard.fields_correct} of {hard.fields} fields.</>}{' '}
      About {Math.round(std.per_invoice_seconds)} seconds and {Math.round(std.per_invoice_usd * 100)} cents a bill at API list prices.
      The bills are rendered for the demo and are cleaner than real scans, so real bills may do worse; that has not been tested. The full
      results are in the evals below.
    </p>
  )
}
