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

## Hard requirements (gates)

These decide keep or drop; they never rank. With `judge_rubric` in `config.json`,
its `hard_gates` list names them; the definitions are here.

1. **`remote_us`:** fully remote and eligible for the user's location. Hybrid,
   onsite, "remote within X miles" and hub-based roles count as not remote.
2. **`level_senior_staff_ic`:** an IC role at a level in `profile.level` (no
   manager/director/junior). In contract mode, judge the scope of the work
   instead, since contract titles rarely state a level.
3. **`salary_max_ge_175k_or_undisclosed`:** drop only when the *disclosed*
   maximum is under `requirements.min_salary`. Undisclosed is kept. In contract
   mode there is no rate gate (see "Rate vs. salary" above).
4. **`no_ads_team`:** anything matching `profile.standing_exclusions` (Ads,
   Advertising, ad-monetization). A preference, not a fit judgment: drop it.
5. **`no_agency_spam_fulltime`:** in fulltime mode, drop staffing-agency or
   marketplace spam ("we place contractors", recruiter reposts with no real
   employer named). In contract mode an agency posting *is* the target; keep it.
6. **`has_frontend_work`:** the role has real frontend work. Drop pure backend
   and frontend stacks the user doesn't use (`profile.fullstack_policy`, e.g.
   Blazor-only, Razor/jQuery-only). React-only and backend-heavy roles are
   **not** dropped here; the rubric scores them low.

Also drop obvious garbage: pure mobile/ML/embedded/Salesforce roles and duplicates.

**Never drop on a guess.** If a gate depends on something the snippet doesn't
say (remote status unclear, level unclear), fetch the full JD (Greenhouse/Ashby/
Lever API, or WebFetch) before dropping.

## Workflow

1. **Gather.** Run the gather script:
   `python "<this skill dir>/find_jobs.py"` (add `--mode contract` for the
   contract lane).
   It writes `job_candidates.json` (fulltime) or `job_candidates_contract.json`
   (contract) — coarse keyword matches + description snippets + salary/rate +
   links. Its `Unreachable feeds (N): ...` line names every feed it could not read.
   When N is not 0, tell the user which companies went unsearched (a 404 usually
   means the company moved ATS or renamed its board); in a run that ends with one
   line (job-funnel backend step 5), add the count to it, e.g. `; 3 feeds unreachable`.
   This stage is dumb on purpose. Without `job_funnel` configured, it also
   auto-excludes companies with tailored docs already on disk (see
   `APPLIED_DIR`/`applied_tokens()` in `find_jobs.py`) -- but that only catches
   roles a resume/cover letter was actually generated for. Cross-check the
   applications tracker (step 3) for the rest. With `job_funnel` configured, the
   script skips that folder scan and `MANUAL_APPLIED`; job-funnel's filter
   (step 2b) covers them.
2. **Pre-filter.** Run `python "<this skill dir>/prefilter.py"` (pass the mode's
   in/out filenames explicitly for contract, e.g. `prefilter.py
   job_candidates_contract.json job_candidates_contract_prefiltered.json`) to
   cheaply narrow the gather output: drops over-level titles (principal/director/
   manager/architect/tech lead/etc.; Staff is kept), enforces the salary floor
   (undisclosed kept as plausible), drops roles with no sign of frontend work (the
   record's `stack` has no frontend term and the title is not frontend, fullstack,
   web, UI or similar), dedupes by (company, title). This is still
   dumb-on-purpose volume reduction, not judging.
   **2b. Filter (only if `config.json` has a `job_funnel` section; otherwise skip
   this step and follow the no-job-funnel flow).** See "job-funnel backend" below.
3. **Judge (this is the real value).** Read the prefiltered file. Without
   `job_funnel`: first read the applications tracker (`resume.applications_tracker_path`
   in `config.json`) and exclude anything already decided there (applied/rejected/
   passed); the gather stage's file-based auto-exclusion is not exhaustive. With
   `job_funnel`, the filter step has already removed handled postings; skip the
   tracker read. Then, for each record:

   **a. Gates.** Apply the hard requirements above. A posting that fails one is
   dropped and not scored.

   **b. Score.** If `config.json` has `judge_rubric`, score every survivor 1-5 on
   each dimension below, using its weights (shown here as the defaults). Without
   `judge_rubric`, skip to step 4 and rank by fit strength in plain words.

   | Dimension | Weight | 5 | 4 | 3 | 2 | 1 |
   |---|---|---|---|---|---|---|
   | `frontend_fit` | 25 | Vue or Angular primary | Vue/Angular alongside React | frontend framework unstated | React primary | frontend under 30% of the role |
   | `backend_fit` | 10 | Node/TS or .NET | | Java/Spring or Python | | unfamiliar stack |
   | `scope_fit` | 10 | migrations, observability, AI tooling, platform | | general feature work | | vague, or a big stretch |
   | `comp` | 15 | disclosed min ≥ `min_salary` | min between $150k and `min_salary` | range spans $150k (min ≤ $150k) | undisclosed | |
   | `freshness_legit` | 15 | first published ≤ 7 days ago | | 8-30 days | 31-60 days | over 60 days, or a repost pattern |
   | `remote_durability` | 10 | remote-first company | | unclear | | company pushing return to office |
   | `network` | 10 | close contact there | | loose contact | | cold |
   | `company_health` | 5 | growing or recently funded | | steady | | layoffs in the last 6 months |

   Use the gap levels (4, 2) only where the row names them; otherwise pick the
   nearer named level.

   - **Stack from `stack`.** Records carry `stack`, the stack terms named anywhere in
     the full JD (the snippet is cut short and is usually the company intro). Score
     `frontend_fit` and `backend_fit` from it as read, not `est`: `vue` or `angular`
     with no `react` is primary (5); with `react` it is alongside React (4) unless the
     title or snippet says which leads; `react` alone is React primary (2); no frontend
     term (or only `svelte`, or only `frontend`, which is frontend work described
     without a framework) is unstated (3). For `backend_fit`, the best one named:
     `node`, `typescript` or `dotnet` 5; `java` or `python` 3; only `go`, `ruby` or
     `php` 1; none named, judge from the snippet. A posting that names every term (a marketplace listing its
     whole catalog) tells you nothing; judge it on the gates.
   - **Freshness from real dates.** Records carry `posted` (the feed's first-published
     date), `updated` and `age_days`; score from `age_days`. When `updated` is well
     after `posted` (Greenhouse `updated_at` vs `first_published`), or an Ashby
     `publishedAt` is years old, report it as an observation ("first posted 290d ago,
     updated 3d ago"), not a verdict of fraud. No `posted` date: unknown.
   - **Network** comes from `judge_rubric.network_file` (default
     `network.local.json` in this skill's directory, gitignored): match the
     posting's company against `company` and `aliases`, ignoring case and suffixes
     like Inc. Listed `close` = 5, `loose` = 3, not listed = 1. If the file is
     missing, network is unknown. Never write a contact's name anywhere: the file
     holds companies only.
   - **Comp from the minimum.** The record's `salary` is the range's maximum; score
     `comp` from the disclosed minimum in the JD. When a JD lists ranges by US
     location tier, use the lowest tier's minimum.
   - **Contract mode:** score `comp` against `contract.min_hourly_rate_target`
     instead (5 = disclosed rate at or above it, 3 = within 15% below it,
     2 = undisclosed, 1 = further below).

   **c. Unknowns.** A dimension with no evidence scores `unknown_default` (3);
   `comp` scores `unknown_default_comp` (2). A score inferred rather than read
   from the feed or JD (for example remote durability from general knowledge of
   the company) is marked **`est`**. A posting with more than `max_est_for_A`
   (1) `est` scores can't reach band A: cap it at B.

   **d. Weighted score and band.** Score = sum of (weight × score) / 100, to two
   decimals. Bands from `judge_rubric.bands`: **A** ≥ 4.2 apply now; **B** 3.5-4.19
   apply; **C** 2.8-3.49 surface with a caveat; **D** under 2.8 omit (not shown, not
   recorded).

   **e. Company health, A and B only.** Score `company_health` 3 for everyone at
   first. For postings in A or B, do a quick layoffs/funding/news lookup (WebSearch
   or WebFetch), rescore, and recompute the band; it may move. If no lookup tool
   can reach news (an unattended run), leave it at 3 and say "health unchecked"
   in the line.

   Prefer precision over volume: a tight list of real fits beats a long noisy one.
4. **Return a banded shortlist**, best score first. Each survivor gets a
   **band line**: `<band> <score to 1 decimal>: <2-3 short facts>`, e.g.
   `B 3.8: comp undisclosed, 40d old` or `A 4.4: Vue + .NET, $190-220k, 3d old`.
   Lead with what pulled the score down (a caveat) when there is one, then the
   strongest fit fact; tag inferred facts `(est)`; keep it under about 70
   characters. Never name a contact; "network: close" is the most it says.
   Without `judge_rubric` there are no bands: the line is a one-phrase reason it
   fits, ranked by fit strength. Either way, this line is the job-funnel `--note`
   (see below).
   In the terminal, show each as
   `<band line> | Title @ Company | $pay (or "salary unconfirmed") | link`.
   In contract mode, show `$rate/hr` when `rate_hourly` is set instead of the
   annualized `salary` figure; don't present the annualized estimate as if it
   were a comparable salary (see the rate-vs-salary caveat above).
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
   each shortlisted posting (with `judge_rubric`, bands A-C only; D is never recorded):
   `funnel record surfaced --url '<url>' --employer '<company>' --title '<title>' --note '<the line from workflow step 4>' --pay '<pay as shown>' --snippet '<short description excerpt>'`
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
