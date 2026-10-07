---
name: job-search
description: Find and triage remote software engineering jobs, either full-time or contract. Gathers postings from remote boards + company ATS feeds, filters to real fits against the user's resume and salary/rate requirements, and drives a one-by-one apply/reject triage.
---

# Job Search & Triage

The user's ask: **"Claude, go find me jobs"** (full-time, default) or
**"find me contract work"** / **"go find contract roles"** (contract mode —
see below). Do the searching, throw out bad matches against their profile +
pay bar, return a curated shortlist, then work them one-by-one (apply or
reject). Never auto-apply — applying is always the user's explicit call.

## Full-time vs. contract mode

`find_jobs.py` takes `--mode fulltime` (default) or `--mode contract`. Ask the
user which they mean if it's ambiguous — some users run both as parallel
lanes, so "find me jobs" without qualification should default to the
full-time lane rather than assuming contract.

Contract mode differs from full-time in a few structural ways, not just a
keyword swap:
- **No seniority requirement.** Contract reqs are routinely titled flatly
  ("Contract Frontend Developer") rather than "Senior ...". Instead it
  requires contract/1099/C2C language in the title or description.
- **Extra source:** We Work Remotely (RSS, no API key) — staffing agencies and
  marketplaces post contract reqs there heavily; it isn't queried in
  full-time mode.
- **Separate output file:** `job_candidates_contract.json`, so a contract
  gather never overwrites a full-time gather or vice versa. Pass the matching
  file through to `prefilter.py` explicitly, e.g.
  `python3 prefilter.py job_candidates_contract.json job_candidates_contract_prefiltered.json`.
- **Rate vs. salary.** Records carry both `salary` (annualized, including a
  disclosed hourly rate × 2080 as an estimate) and `rate_hourly` (the raw
  figure, when disclosed). When judging, treat the annualized figure as a
  rough floor check only — 1099 has no benefits/PTO and ~15.3% SE tax on top,
  so a contract rate isn't apples-to-apples with a W-2 salary. As a rule of
  thumb, direct 1099 tends to run ~1.3–1.4× the W-2-equivalent hourly to
  cover that gap; most postings won't disclose a rate at all, so don't
  over-filter on it.
- **What this script still can't reach:** pure W-2 staffing agencies (Kforce,
  TEKsystems, Insight Global, Robert Half, Dexian) and vetted marketplaces
  (Braintrust, Toptal) have no public feed to gather from — Braintrust's own
  job list is gated behind "Certified Talent" membership, confirmed not a
  public board. Those stay a manual registration/application step outside
  this tool; mention this to the user rather than implying the gather stage
  covers them.

## User profile

Before running, you need the user's profile. Check if a config or memory
contains their details, or ask them directly for:

- **Level:** target seniority (e.g. Senior / Staff / Principal / Lead)
- **Stack:** primary languages, frameworks, and tools
- **Differentiators:** what sets them apart (leadership scope, domain expertise, etc.)
- **Minimum salary:** base compensation floor
- **Location:** remote preference and country/region eligibility

## Hard requirements

1. **Salary** at or above the user's minimum (base). If undisclosed, keep only
   if the level/company makes it plausible — flag as "salary unconfirmed".
2. **Fully remote**, eligible for the user's location. Drop hybrid/onsite-only
   and ineligible-location roles (flag any where eligibility is unclear).
3. **Appropriate level** engineering role that genuinely uses the user's stack
   (in contract mode: appropriate scope/seniority for the work itself, since
   contract titles rarely state a level).
4. **Standing exclusions.** Check `profile.standing_exclusions` in `config.json`
   for team/domain types the user has explicitly ruled out (not a fit judgment,
   a preference) -- exclude or prominently flag these rather than quietly
   including them.

## Workflow

1. **Gather.** Run the gather script:
   `python "<this skill dir>/find_jobs.py"` (add `--mode contract` for the
   contract lane).
   It writes `job_candidates.json` (fulltime) or `job_candidates_contract.json`
   (contract) — coarse keyword matches + description snippets + salary/rate +
   links. This stage is dumb on purpose. Without `job_funnel` configured, it also
   auto-excludes companies with tailored docs already on disk (see
   `APPLIED_DIR`/`applied_tokens()` in `find_jobs.py`) -- but that only catches
   roles a resume/cover letter was actually generated for. Cross-check the
   applications tracker (step 3) for the rest. With `job_funnel` configured, the
   script skips that folder scan and `MANUAL_APPLIED`; job-funnel's filter
   (step 2b) covers them.
2. **Pre-filter.** Run `python "<this skill dir>/prefilter.py"` (pass the mode's
   in/out filenames explicitly for contract, e.g. `prefilter.py
   job_candidates_contract.json job_candidates_contract_prefiltered.json`) to
   cheaply narrow the gather output: drops over-level titles (staff/principal/
   director/manager/architect/tech lead/etc.), enforces the salary floor
   (undisclosed kept as plausible), dedupes by (company, title). This is still
   dumb-on-purpose volume reduction, not judging.
   **2b. Filter (only if `config.json` has a `job_funnel` section; otherwise skip
   this step and follow the no-job-funnel flow).** See "job-funnel backend" below.
3. **Judge (this is the real value).** Read the prefiltered file. For
   each record, read the snippet and decide true fit against the user's profile +
   hard requirements. Without `job_funnel`: first, read the applications tracker (its path is in
   `resume/applied_docs_dir` in `config.json`) and exclude anything already decided
   there (applied/rejected/passed) -- path is `resume.applications_tracker_path`
   in `config.json`. Don't rely solely on the gather stage's file-based
   auto-exclusion, it's not exhaustive. With `job_funnel`, the filter step has
   already removed handled postings; skip the tracker read. **Aggressively drop garbage:**
   wrong level, non-remote, obvious stack mismatch (e.g. pure mobile/ML/embedded/
   Salesforce), duplicates, sub-minimum-salary/rate when disclosed, and anything
   matching the user's standing exclusions (see profile/config for team- or
   domain-specific ones). In **fulltime mode**, also drop staffing-agency/
   contractor-marketplace spam ("we place contractors," recruiter-repost
   listings with no real employer named) — that's noise there. In **contract
   mode**, don't drop those — a staffing-agency or marketplace posting *is*
   the target; only drop it for the usual reasons (stack mismatch, wrong
   level, non-remote, etc.), not for being agency-sourced.
   Prefer precision over volume — a tight list of real fits beats a long noisy one.
4. **Return a ranked shortlist.** For each survivor, one line:
   `Title @ Company — $salary (or "salary unconfirmed") — 1-phrase why it fits — link`.
   In contract mode, show `$rate/hr` when `rate_hourly` is set instead of the
   annualized `salary` figure — don't present the annualized estimate as if it
   were a comparable salary (see the rate-vs-salary caveat above).
   Rank by fit strength. Note any caveats (stack stretch, scope stretch, eligibility
   unclear). If the snippet is too thin to judge, fetch the full JD (Greenhouse/Ashby/
   Lever API or WebFetch) before deciding.
5. **Triage one-by-one** (without `job_funnel`; with it, see "job-funnel backend"
   below). Go through the shortlist with the user. For each: **apply**
   or **reject**. Keep it quick. Log every decision in the applications tracker
   (date, company, role, salary, status, link, notes) -- this is what step 3's
   cross-check depends on for roles that never get tailored docs generated.
6. **On "apply":** run `/resume-cover <job-posting-url>` to tailor from the user's
   master resume (writes Markdown, plus a submission-ready PDF). Be honest — never
   fabricate skills; surface real gaps and flag anything that needs the user's
   confirmation.

   **Model routing for the cover letter prose:** don't draft the letter inline on the
   session model. Gather the real story facts from the user first (ask, don't guess), fetch
   the JD text, then hand the first draft to a fresh Opus subagent (Agent tool,
   `subagent_type: general-purpose`, `model: opus`; forks inherit the session model, so
   they won't do). Brief it with the JD text, the candidate facts (no embellishment),
   any voice rules the user has given (from memory or config), and any complaints
   about earlier drafts. In the JSON schema example, use the schema's real `signoff`
   value ("Thank you for your consideration.") or omit it, never the name; the generator
   appends "Sincerely," plus the full name itself. The session model keeps the JD fetch,
   the schema mapping, and all iterative edits after the first draft. Judging (step 3)
   stays on the session model.

## job-funnel backend (optional)

Only when `config.json` has a `job_funnel` section (`cli`, `node`, `to_apply_url`);
`config.example.json` deliberately has none, so the backend is opt-in.
**Without that section, ignore this whole section: the skill behaves as described
above.** job-funnel is a local job-search funnel tracker with a CLI and a web UI.

Each Bash call is a fresh shell, so define a helper inside every call that uses it:

```bash
funnel() { '<node>' '<cli>' "$@"; }   # values from config.json job_funnel
```

Steps (run after the pre-filter; use the contract filenames in contract mode):

1. **Filter, don't import.** `funnel filter <prefiltered.json> <prefiltered.json>`
   (in place). There is no backup-import step: job-funnel keeps its application
   data current itself.
2. **Read the freshness line.** `filter` prints one line after its summary giving
   the date of the newest application entry it knows (or that there are none).
   Ask the user only if that date looks older than their most recent application,
   since applied postings could then look new.
3. **Stop on failure.** If `filter` exits non-zero or the output file is missing,
   stop and tell the user. Never show an unfiltered list.
4. **Judge** the filtered file as in workflow step 3, then **record details** for
   each shortlisted posting:
   `funnel record surfaced --url '<url>' --employer '<company>' --title '<title>' --note '<one-phrase why it fits>' --pay '<pay as shown>' --snippet '<short description excerpt>'`
   adding `--lane contract` in contract mode. Single quotes keep the shell from
   expanding `$` (`'$180k'`, not `"$180k"`), so write any `'` inside a value as
   `'\''` (e.g. `--snippet 'We'\''re hiring'`); snippets often contain one.
5. **End at the page.** By default, finish with one line and no one-by-one triage,
   e.g. `9 new postings on the To Apply page: <to_apply_url>`. This replaces
   workflow steps 4-5 (the long terminal shortlist and triage).
6. **Optional chat triage** (only if the user asks, e.g. "triage with me"): the
   one-by-one flow, where each decision writes the same records the page would:
   - **Pass:** `funnel record passed …`
   - **Pass Company:** `funnel block "<Company>"`, then `funnel record passed …`
   - **Save:** `funnel record saved …`
   - **Apply:** record nothing. The user logs applications in their own
     application log, which job-funnel reads. Never draft, suggest or fill in an
     entry in that log. Then continue with workflow step 6 (`/resume-cover`).

## Configuration

Edit the CONFIG section at the top of `find_jobs.py` to customize:

- `SENIORITY`, `ROLE`, `TECH` — coarse keyword filters for titles/descriptions (fulltime mode)
- `CONTRACT_TERMS` — coarse keyword filter that replaces `SENIORITY` in contract mode
- `WWR_FEEDS` — We Work Remotely RSS category URLs queried in contract mode
- `GREENHOUSE`, `ASHBY`, `LEVER` — company ATS tokens (unknown tokens are skipped safely; used in both modes)
- `MANUAL_APPLIED` — set of company name tokens to exclude (already applied); skipped when `job_funnel` is configured
- `APPLIED_DIR` — directory to scan for tailored resume/cover letter docs (auto-exclusion); skipped when `job_funnel` is configured
- `job_funnel` (in `config.json`, optional) — enables the job-funnel backend above

## Notes / maintenance

- Sources: RemoteOK + Remotive (cross-company remote) and per-company Greenhouse/
  Ashby/Lever feeds (both modes); We Work Remotely RSS (contract mode only).
  There is no universal job API; LinkedIn/Indeed are not scrapable. To widen
  coverage, add company ATS tokens to the CONFIG lists in `find_jobs.py`
  (unknown tokens are skipped safely).
- Salary filtering is best-effort (many posts omit pay). The script extracts pay
  from text; when absent, Claude uses level/company judgment. Contract-rate
  extraction (`$NN/hr`) is even sparser than salary disclosure — most contract
  reqs, especially agency-posted ones, withhold rate until a screen; standard
  negotiating advice is not to quote first, so let the client or agency name
  a number.
- Pure W-2 staffing agencies (Kforce, TEKsystems, Insight Global, Robert Half,
  Dexian) and vetted marketplaces (Braintrust, Toptal) have no public feed —
  they're a manual registration step, not something `find_jobs.py` gathers.
