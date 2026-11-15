// The walkthrough: a morning in accounts payable, six steps on the real screens. Each step says what
// a finance team struggles with (and where any number in it comes from), what the AI does about it,
// and what code and people do, then opens the bill or the screen that shows it. The AI lines say what
// Claude did in the recorded runs the demo replays (replays/claude-opus-5-5-low-run2, 2026-11-14). The numbers are copied from the publishers' own
// pages, read 2026-11-14; a pytest checks every bill named here is one of the samples.

import { SITE } from './site'

export type TourStep = {
  title: string
  struggle: string
  source: { label: string; url: string } | null
  ai: string // what Claude does: reading, looking things up, explaining, drafting
  app: string // what code checks and what a person decides
  go: { tab: 'bills' | 'audit'; bill?: string }
}

export const ARDENT = {
  label: 'Ardent Partners, The State of ePayables 2025',
  url: 'https://payablesplace.ardentpartners.com/2026/01/state-of-epayables-part-nine-ap-benchmarks-and-best-in-class-performance/',
}
export const AFP = {
  label: 'AFP 2025 Payments Fraud and Control Survey, 521 respondents',
  url: 'https://www.financialprofessionals.org/about/learn-more/press-releases/Details/survey-79-percent-of-organizations-were-victims-of-attempted-or-actual-payments-fraud-activity-in-2024',
}
// The FBI's own report is a PDF that was not opened; the figures are as Nacha quotes them
export const FBI = {
  label: 'FBI IC3 2024 report, as quoted by Nacha',
  url: 'https://www.nacha.org/news/fbis-ic3-finds-almost-85-billion-lost-business-email-compromise-last-three-years',
}

export const TOUR: TourStep[] = [
  {
    title: 'Monday morning: the pile of bills',
    struggle:
      'Someone types each supplier bill in and checks it by hand against the purchase order and the delivery slip. Across the ' +
      'accounts-payable teams surveyed, 18.4% of bills have a problem, and the average bill takes 8.2 days and $9.84 to process.',
    source: ARDENT,
    ai: 'Claude reads every bill, PDF or phone photo, into vendor, lines, totals and bank details, with no template per vendor, and quotes the line on the document each value came from. Nobody types anything in.',
    app:
      "Code checks each quote is really in the PDF (a phone photo is checked by eye), then checks the bill against the " +
      "purchase order, the delivery, past bills and the bank details on file. This week's " + SITE.recorded.n + " bills are done: " +
      'the clean ones wait for one click, and each problem bill says what is wrong and what to do next.',
    go: { tab: 'bills' },
  },
  {
    title: 'A clean bill should take one click',
    struggle: 'Clean bills wait in the same queue as the problem ones, and every one of them still needs someone to check it and sign off.',
    source: null,
    ai: 'This bill has no purchase order, so Claude also suggests the account to book it to, with its reason: electricity for the roastery and cafés, a utilities expense.',
    app: "Code accepts the account only if it is in the chart of accounts and fits this kind of vendor, and checks the amount is within the usual range. Approve it as the clerk: it is booked in the company's books, and added to QuickBooks when QuickBooks is connected.",
    go: { tab: 'bills', bill: 'UTL-4411' },
  },
  {
    title: 'The overcharge',
    struggle:
      'Catching it means comparing every line with the purchase order, and then someone has to chase the vendor. Accounts-payable staff ' +
      'spend 21.9% of their time dealing with suppliers, in no small part because of problem bills.',
    source: ARDENT,
    ai: "Claude looks up the purchase order, the delivery and the vendor record, works out that the price is the only problem (all 5,000 cups arrived and the bank details match) and explains it in plain words: the digging a clerk would otherwise do by hand. It also drafted an email asking for a credit, but it searched only the company's books, so it did not see the credit the vendor already sent.",
    app: 'Code found the overcharge by comparing every line with the purchase order, $200, then matched it to credit memo CM-PKG-0412 in the queue, which names this bill. So the suggested next step approves the bill against the credit, and the credit is approved too: together they pay the agreed price. Until the credit is read, the step is to hold for a corrected bill.',
    go: { tab: 'bills', bill: 'PKG-20817' },
  },
  {
    title: 'The bill that was already paid',
    struggle: 'Vendors resend bills, and a copy can arrive by post after the email. Unless every bill is checked against what was already paid, the copy gets paid too.',
    source: null,
    ai: "Claude looks up the vendor's paid bills, finds the earlier copy of this bill (dated Oct 14) among them, and drafts a note telling the vendor it was already paid.",
    app: 'Code matched the bill number against the paid bills. The suggested next step rejects it, with the reason on record.',
    go: { tab: 'bills', bill: 'DAI-5521' },
  },
  {
    title: 'The new bank account',
    struggle:
      'In 2024, 79% of the organizations surveyed saw attempted or actual payments fraud, and 45% reported criminals pretending to be a ' +
      'vendor. Only 22% got back 75% or more of what was lost.',
    source: AFP,
    ai: 'Claude checks the vendor record, explains what changed, and drafts an email that tells the vendor the change will be confirmed by calling the number already on file, and asks them not to send new bank details by email.',
    app: 'Code caught the new account. Only the controller can approve it, and only after calling the vendor on the number already on file. Try approving it as the clerk: the app refuses.',
    go: { tab: 'bills', bill: 'REP-3307' },
  },
  {
    title: "Month end: the auditor's questions",
    struggle: 'At month end someone has to show who approved each payment, when and why, and that nobody changed the record afterwards.',
    source: null,
    ai: "Each AI step is in the trail with the model calls and tokens it used, and each bill shows its time and cost at the bottom of its page. Claude's tools can look records up and save a draft email, nothing else: it cannot approve, book or pay anything, so even a bill written to fool it cannot make it pay.",
    app: 'Every check, decision and reason is in the trail too, each row chained to the one before. Press Verify to check that no row has been edited since.',
    go: { tab: 'audit' },
  },
]
