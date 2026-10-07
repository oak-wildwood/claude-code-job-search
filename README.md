# claude-code-job-search

Based on [Tom Colarusso's claude-code-job-search](https://github.com/Yodablues/claude-code-job-search) (MIT), extended with a contract/1099 search mode, a Markdown+PDF resume-cover pipeline, and assorted fixes. See `LICENSE` for copyright details.

A [Claude Code](https://claude.ai/code) skill that finds remote software engineering jobs — full-time or contract — filters them against your resume and salary/rate requirements, and walks you through a triage workflow — all from your terminal.

It queries public job APIs (RemoteOK, Remotive, Greenhouse, Ashby, Lever, and — contract mode only — We Work Remotely), applies a coarse keyword filter, then hands the results to Claude to judge real fit against your profile. You get a ranked shortlist and go through it one-by-one: apply or reject.

## Skills included

### `/job-search` — Find and triage jobs

- **Two modes:** `--mode fulltime` (default) or `--mode contract` — contract mode drops the seniority requirement, requires contract/1099/C2C language instead, and adds We Work Remotely as a source. Outputs go to separate files (`job_candidates.json` vs. `job_candidates_contract.json`) so gathering one never clobbers the other.
- **Automated sourcing** from 200+ company ATS feeds + RemoteOK + Remotive (+ We Work Remotely in contract mode), parallelized
- **Coarse pre-filter** by seniority (or contract language), role type, tech stack, and remote status
- **Claude-powered fit scoring** against your actual profile (not just keyword matching)
- **Already-applied detection** — skips companies you've already applied to (via tailored resume files on disk or a manual exclusion list), or, with the optional job-funnel backend, via its filter and company blocklist
- **Not covered:** pure W-2 staffing agencies (Kforce, TEKsystems, Insight Global, Robert Half, Dexian) and vetted marketplaces (Braintrust, Toptal) have no public feed to query — those stay a manual registration step.

### `/resume-cover` — Tailored resume & cover letter

- **Fetches the job posting** and extracts requirements automatically
- **Reads your master resume** as the single source of truth
- **Tailors the resume** — rewrites summary, reorders bullets, mirrors the JD's language
- **Writes a cover letter** with bold lead-in paragraphs mapping your experience to their requirements
- **Outputs Markdown** (source of truth) with a submission-ready PDF rendered on demand via headless Chrome
- Never fabricates experience — addresses gaps honestly

## Installation

```bash
# Clone into your Claude Code skills directory
git clone https://github.com/oak-wildwood/claude-code-job-search ~/.claude/skills/job-search
```

### Job search setup

Edit the CONFIG section at the top of `find_jobs.py`:

- `SENIORITY`, `ROLE`, `TECH` — coarse keyword filters for titles and descriptions (fulltime mode)
- `CONTRACT_TERMS` — coarse keyword filter that replaces `SENIORITY` in contract mode
- `WWR_FEEDS` — We Work Remotely RSS category URLs queried in contract mode
- `GREENHOUSE`, `ASHBY`, `LEVER` — company ATS tokens (200+ included, add more freely — unknown tokens are skipped; used in both modes)
- `MANUAL_APPLIED` — set of company name tokens to exclude (already applied)
- `APPLIED_DIR` — directory to scan for tailored resume/cover letter files (auto-exclusion)

Both of the last two are kept for users without job-funnel and are skipped when `config.json` has a `job_funnel` section.

### Optional: job-funnel backend

job-funnel is a local job-search funnel tracker with a CLI and a web UI. It is opt-in: `config.example.json` leaves it out on purpose, so copying the example never turns it on. If you use it, add this section to your git-ignored `config.json` (in this skill's directory):

```json
"job_funnel": {
  "cli": "/path/to/job-funnel/src/cli.ts",
  "node": "node",
  "to_apply_url": "http://localhost:8766/to-apply"
}
```

- `cli` is the job-funnel CLI to run, as an absolute path (`~` is not expanded). Point it at a pinned checkout, such as the one job-funnel's serve agent runs from, rather than a working tree, so unmerged branches never touch real data.
- `node` is the Node executable.
- `to_apply_url` is where the To Apply page is served.

With this section present, a run:
1. filters the pre-filtered postings through job-funnel's `filter` (dropping ones already applied or passed; no backup import is needed) and stops if it fails, rather than showing an unfiltered list;
2. records each shortlisted posting with its note, pay and snippet (`record surfaced`);
3. ends with one line pointing at the To Apply page instead of a long terminal triage.

Say "triage with me" for the one-by-one chat flow: Pass, Pass Company (blocks the company), and Save write the same records the page would; Apply records nothing, since you log applications in your own application log, which job-funnel reads.

Claude defines `funnel` as a shell function inside each Bash call (e.g. `funnel() { node /path/to/cli.ts "$@"; }`), because each call is a fresh shell.

**Without a `job_funnel` section, nothing changes.**

### Resume & cover letter setup

```bash
cd ~/.claude/skills/job-search/resume-cover
cp config.example.json config.json
```

Edit `config.json` with your details:

```json
{
  "name": "Your Name",
  "location": "City, State",
  "email": "you@example.com",
  "phone": "555-555-5555",
  "linkedin": "linkedin.com/in/your-profile",
  "website": "yoursite.com",
  "github": "github.com/you",
  "source_resume": "/path/to/Your_Resume.md",
  "output_dir": "/path/to/output/directory"
}
```

## Usage

In Claude Code, just say:

```
find me jobs
```

Or any variation: "go find jobs", "any new roles", "search for jobs".

For contract work, say so explicitly: "find me contract work" / "go find
contract roles" (runs `find_jobs.py --mode contract`, a separate lane from
the full-time search).

Claude will:
1. Run the gather script to pull fresh postings
2. Read the results and aggressively filter against your profile
3. Present a ranked shortlist
4. Walk through each match for you to apply or reject

When you say "apply" on a role:

```
/resume-cover <job-posting-url>
```

Claude will fetch the JD, tailor your resume and cover letter, and output Markdown files (plus PDFs, ready to submit).

## Requirements

- [Claude Code](https://claude.ai/code) (CLI, desktop app, or IDE extension)
- Python 3.8+ (stdlib only — no pip installs needed)
- Google Chrome or Chromium (macOS only, for PDF rendering via `--pdf`; Markdown output works without it)

## Adding company ATS feeds

The script queries company career pages via their public ATS APIs. To add companies, put their board token/name in the appropriate list in `find_jobs.py`:

- **Greenhouse**: The URL slug from `boards.greenhouse.io/{token}` — e.g. `"stripe"`, `"discord"`
- **Ashby**: The company name from their job board — e.g. `"Linear"`, `"Vercel"`
- **Lever**: The URL slug from `jobs.lever.co/{token}` — e.g. `"netflix"`

Unknown or invalid tokens are silently skipped, so it's safe to add speculative entries. 200+ companies are included out of the box.

## How it works

```
"find me jobs"
    │
    ├── find_jobs.py              # GATHER: hits APIs, coarse keyword filter
    │   └── job_candidates.json   # raw candidates (gitignored)
    │
    └── Claude (SKILL.md)         # JUDGE: reads candidates, scores fit,
                                  # presents shortlist, drives triage

/resume-cover <url>
    │
    ├── WebFetch                  # Fetch & parse the job posting
    ├── Source resume             # Read master resume as truth
    ├── Claude                    # Tailor content to the JD
    └── generate_resume_cover.py  # Write .md (+ .pdf via headless Chrome)
```

## License

MIT
