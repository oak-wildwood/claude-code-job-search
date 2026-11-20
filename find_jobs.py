#!/usr/bin/env python3
"""
find_jobs.py — GATHER stage for the job-search skill.

This script only casts a wide net and does a coarse pre-filter. It deliberately
does NOT decide fit quality — Claude reads the emitted snippets and judges each
against the candidate's resume + salary/rate bar.

Two modes, picked with --mode:
  fulltime (default) — seniority + engineering role + relevant tech + remote.
    Writes job_candidates.json (unchanged filename, back-compat).
  contract — engineering role + relevant tech + remote + contract/1099/C2C
    language, seniority NOT required (contract reqs are often titled flatly,
    e.g. "Contract Frontend Developer"). Adds We Work Remotely (agencies post
    contract reqs there heavily) and Himalayas (public search API, no auth,
    filters server-side on employment_type=Contractor + country=US) and
    filters Remotive/RemoteOK/Himalayas by their native job-type/tag fields
    in addition to text. Writes job_candidates_contract.json so a contract
    gather never clobbers a fulltime one (and vice versa).

Output: writes the mode's JSON file (full records w/ snippets) next to this
script and prints a short summary. No third-party deps (urllib + stdlib xml only).
Edit CONFIG to tune criteria or add companies (unknown ATS tokens are skipped).

Not covered here: pure W-2 staffing agencies (Kforce, TEKsystems, Insight
Global, Robert Half, Dexian) and vetted marketplaces (Braintrust, Toptal,
A.Team, Gun.io). None expose a public feed -- Braintrust's own job list is
gated behind "Certified Talent" membership, not a public board; A.Team and
Gun.io are apply-and-wait networks with no browsable board either. Those are
a manual registration/application step, not something this script can gather.
"""

import argparse
import datetime
import email.utils
import json
import os
import re
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

# ----------------------------- CONFIG ---------------------------------------
SENIORITY = ["senior", "staff", "principal", "lead", "sr.", "sr ", "distinguished"]
ROLE = ["engineer", "developer", "swe", "software"]
TECH = ["vue", "angular", "react", "typescript", "javascript", "full stack",
        "fullstack", "full-stack", "front-end", "frontend", "node", "python"]
# Deliberately no ".net"/"c#" here: a .NET-only posting isn't a fit, and
# .NET + Vue/Angular shops already match via "vue"/"angular" above. The
# "any backend is fine as long as the frontend is Vue/Angular" rule is
# enforced at the judge step (profile.fullstack_policy in config.json).
US_HINTS = ["us", "usa", "u.s", "united states", "anywhere", "worldwide",
            "north america", "remote"]
# contract mode: replaces the SENIORITY requirement (title/desc must show
# this instead of a seniority word — contract reqs skip seniority in the
# title far more often than FT postings do)
CONTRACT_TERMS = ["contract", "contractor", "contract-to-hire", "c2h", "1099",
                   "freelance", "consultant", "consulting", "corp-to-corp",
                   "corp to corp", "c2c", "w2 contract", "temp-to-hire",
                   "temporary"]
# "consultant"/"consulting" are dropped for TITLE matching specifically --
# live-tested 2026-09-23: they're common in legitimate FT job titles
# ("Senior Consulting Engineer", "Solutions Consultant") with no relation to
# 1099/gig work, so they produced title-level false positives even though
# the boilerplate false-positive problem (see coarse_match's docstring) is
# fixed. Still used for body-context matching, where they're one signal
# among many rather than the sole match.
CONTRACT_TITLE_TERMS = [t for t in CONTRACT_TERMS if t not in ("consultant", "consulting")]
# Bare "contract"/"contractor" are dropped for BODY matching (WWR/RemoteOK/
# Remotive) -- live-tested 2026-09-23: on real postings these words show up
# constantly describing the *business*, not the job's employment type
# ("roofing contractors" as the customer base, "contract manufacturer" as the
# company's own business type, "contractor referral marketplace" as the
# product, "contractors never handle production data" as a security policy).
# 3 of 4 real WWR gather hits in one test run were this exact false positive.
# Replaced with more specific phrases that don't collide with ordinary business
# language. Kept for TITLE matching, where "(Contract)" in a title is precise.
CONTRACT_BODY_TERMS = [t for t in CONTRACT_TERMS if t not in ("contract", "contractor")] + [
    "contract-based", "contract based", "contract position", "contract role",
    "contract engagement", "on a contract basis", "contract job", "hourly contract",
]
WWR_FEEDS = [
    "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-front-end-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
]
# Himalayas' public search API has no auth and takes employment_type/country
# as real server-side filters (verified 2026-09-24), unlike RemoteOK/Remotive
# which only offer text/tag signal for "contract". One query per keyword since
# the API has no OR-of-terms search; keep this list narrow to the user's
# actual stack rather than mirroring the broad TECH list above.
HIMALAYAS_QUERIES = ["vue", "react", "typescript", "angular", "frontend", "node",
                     "fullstack", ".net"]

GREENHOUSE = [
    # Every token answered with at least one job on 2026-11-19. A token that 404s is
    # reported by the gather (see FAILED_FEEDS), so prune or fix it when one shows up.
    "adyen", "affirm", "airbnb", "airtable", "algolia", "anthropic", "asana",
    "assemblyai", "attentive", "automatticcareers", "bitwarden", "block", "braze",
    "brex", "buildkite", "calendly", "calm", "carta", "chime", "circleci", "cloudflare",
    "cockroachlabs", "coinbase", "collibra", "comet", "contentful", "coursera", "cribl",
    "cultureamp", "customerio", "dashlane", "databricks", "datadog", "descope",
    "discord", "dropbox", "duolingo", "elastic", "endorlabs", "faire", "fanaticsinc",
    "fastly", "figma", "fingerprint", "fivetran", "gemini", "gitlab", "grafanalabs",
    "greenhouse", "gusto", "harnessinc", "highnote", "honeycomb", "hootsuite",
    "instacart", "intercom", "justworks", "labelbox", "later", "lattice",
    "launchdarkly", "lithic", "mercury", "mixpanel", "mongodb", "narvar", "netlify",
    "newrelic", "ngrokinc", "offerup", "okta", "oscar", "pagerduty", "payoneer",
    "peloton", "pinterest", "planetscale", "ramp", "reddit", "remote", "robinhood",
    "roblox", "samsara", "scaleai", "seatgeek", "shein", "shipbobinc", "sigmacomputing",
    "smartsheet", "stabilityai", "stockx", "storyblok", "stripe", "tailscale", "toast",
    "togetherai", "treasuryprime", "twilio", "typeform", "udemy", "unframe", "veracode",
    "veracyte", "vercel", "vonage", "wise", "wizinc", "zscaler",
]
ASHBY = [
    # Every token answered with at least one job on 2026-11-19. A token that 404s is
    # reported by the gather (see FAILED_FEEDS), so prune or fix it when one shows up.
    "1password", "airbyte", "airwallex", "amplitude", "anyscale", "Ashby", "Atlan",
    "AuthZed", "benchling", "Braintrust", "bubble", "buffer", "capsule", "Clerk",
    "clickhouse", "clickup", "cognition", "Cohere", "Column", "Cube", "Cursor",
    "Deepgram", "docker", "Doppler", "Drata", "Dust", "ElevenLabs", "Fig",
    "frontcareers", "fullstory", "gamma", "Gray Swan AI", "handshake", "Harvey",
    "helpscout", "Hex", "Hightouch", "Infisical", "Inngest", "Knock", "LangChain",
    "Lightdash", "lightspeedhq", "Linear", "litmus", "LlamaIndex", "midjourney",
    "Mintlify", "miro", "Modal", "moderntreasury", "motherduck", "mural", "Neon",
    "nerdwallet", "Notion", "OneSchema", "OpenAI", "Oyster", "perplexity", "Pinecone",
    "Plaid", "Plain", "Plane", "poolside", "poshmark", "PostHog", "Prefect", "prelude",
    "Railway", "Ramp", "Render", "Replit", "Resend", "roboflow", "runway", "sanity",
    "Secureframe", "semgrep", "sentry", "snowflake", "snyk", "spruceid", "substack",
    "Supabase", "Svix", "Synctera", "Temporal", "Tldraw", "triggerdev", "Unit", "Vanta",
    "vantage", "Warp", "Weaviate", "webflow", "WorkOS", "writer", "WunderGraph",
    "zapier", "Zed",
]
LEVER = [
    # Every token answered with at least one job on 2026-11-19. A token that 404s is
    # reported by the gather (see FAILED_FEEDS), so prune or fix it when one shows up.
    "15five", "aerostrat", "angellist", "brilliant", "fly", "gopuff", "immuta",
    "metabase", "ro", "twingate", "veeva", "zilliz",
]

# Display names for feed tokens that aren't the company's name as written (a board slug like
# "wizinc", or a lowercase Ashby slug). Tokens not listed: Greenhouse and Lever use token.title(),
# Ashby uses the name as written.
COMPANY_NAMES = {
    "automatticcareers": "Automattic",
    "cultureamp": "Culture Amp",
    "customerio": "Customer.io",
    "endorlabs": "Endor Labs",
    "fanaticsinc": "Fanatics",
    "harnessinc": "Harness",
    "ngrokinc": "ngrok",
    "newrelic": "New Relic",
    "scaleai": "Scale AI",
    "shipbobinc": "ShipBob",
    "sigmacomputing": "Sigma Computing",
    "stabilityai": "Stability AI",
    "togetherai": "Together AI",
    "wizinc": "Wiz",
    "grafanalabs": "Grafana Labs",
    "cockroachlabs": "Cockroach Labs",
    "treasuryprime": "Treasury Prime",
    "launchdarkly": "LaunchDarkly",
    "gitlab": "GitLab",
    "mongodb": "MongoDB",
    "circleci": "CircleCI",
    "pagerduty": "PagerDuty",
    "offerup": "OfferUp",
    "stockx": "StockX",
    "1password": "1Password",
    "airbyte": "Airbyte",
    "airwallex": "Airwallex",
    "amplitude": "Amplitude",
    "anyscale": "Anyscale",
    "benchling": "Benchling",
    "bubble": "Bubble",
    "buffer": "Buffer",
    "capsule": "Capsule",
    "clickhouse": "ClickHouse",
    "clickup": "ClickUp",
    "cognition": "Cognition",
    "docker": "Docker",
    "frontcareers": "Front",
    "fullstory": "FullStory",
    "gamma": "Gamma",
    "handshake": "Handshake",
    "helpscout": "Help Scout",
    "lightspeedhq": "Lightspeed",
    "midjourney": "Midjourney",
    "miro": "Miro",
    "moderntreasury": "Modern Treasury",
    "motherduck": "MotherDuck",
    "mural": "Mural",
    "nerdwallet": "NerdWallet",
    "perplexity": "Perplexity",
    "poolside": "Poolside",
    "poshmark": "Poshmark",
    "roboflow": "Roboflow",
    "runway": "Runway",
    "sanity": "Sanity",
    "semgrep": "Semgrep",
    "sentry": "Sentry",
    "snowflake": "Snowflake",
    "snyk": "Snyk",
    "substack": "Substack",
    "triggerdev": "Trigger.dev",
    "vantage": "Vantage",
    "webflow": "Webflow",
    "writer": "Writer",
    "zapier": "Zapier",
    "15five": "15Five",
    "angellist": "AngelList",
    "aerostrat": "Aerostrat",
    "unframe": "Unframe",
    "seatgeek": "SeatGeek",
    "fingerprint": "Fingerprint",
    "prelude": "Prelude",
    "litmus": "Litmus",
    "spruceid": "SpruceID",
}

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept": "application/json,text/plain,*/*"}
TIMEOUT = 20
RETRIES = 3                # retry transient failures / rate limits with backoff
# Companies manually marked as already applied (add your own). Only used when
# config.json has no job_funnel section; with job-funnel, its filter and company
# blocklist cover this, so this set is skipped.
MANUAL_APPLIED = set()


def _load_local_config():
    """Personal values (real name, real local path) live only in the gitignored
    config.json, never hardcoded here -- this script is published/shared, config.json
    isn't. Missing config.json (e.g. a fresh clone) just disables auto-exclusion."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


_local_cfg = _load_local_config()
_resume_cfg = _local_cfg.get("resume", {})
# Optional job-funnel backend: when configured, its `filter` step (applied and passed
# postings) and company blocklist replace the folder scan and MANUAL_APPLIED below.
# Users without a job_funnel section keep both exactly as before.
JOB_FUNNEL = bool(_local_cfg.get("job_funnel"))
# Directory scanned to auto-exclude companies already applied to (tailored docs present).
# From config.json's resume.applied_docs_dir; empty disables the auto-exclusion.
# Skipped when job_funnel is configured.
APPLIED_DIR = _resume_cfg.get("applied_docs_dir", "")


def _pattern_to_regex(pattern):
    """Turn a config.json filename pattern like 'Name_Resume_{company}.md' into a
    regex with the company name captured and a loosened extension (md/pdf/docx --
    whichever a run actually wrote, not just the one pattern names)."""
    esc = re.escape(pattern).replace(re.escape("{company}"), "(.+)")
    return re.sub(r"\\\.(?:md|pdf|docx)$", r"\\.(?:md|pdf|docx)", esc)


_APPLIED_REGEXES = [re.compile(_pattern_to_regex(p), re.I)
                     for p in (_resume_cfg.get("resume_filename_pattern", ""),
                               _resume_cfg.get("cover_letter_filename_pattern", ""))
                     if p]
# Filename suffix tokens that are role descriptors / housekeeping, not companies
EXCLUDE_STOPWORDS = {"backup", "principal", "master"}
SNIPPET_LEN = 700
# ----------------------------------------------------------------------------


# Feeds that could not be read this run, as (source, name, reason). Each fetcher records its
# own failure here instead of returning nothing silently, so a renamed or dead ATS token
# shows up in the gather's output rather than quietly shrinking the search.
FAILED_FEEDS = []


def _failed(source, name, err):
    code = getattr(err, "code", None)
    FAILED_FEEDS.append((source, name, f"HTTP {code}" if code else type(err).__name__))


def get(url):
    last = None
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=TIMEOUT) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001 - transient (rate limit / network); back off
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise last


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def applied_tokens():
    """Company tokens from tailored docs in APPLIED_DIR, to skip already-applied roles.
    Empty when job_funnel is configured (its filter/blocklist handle this instead)."""
    toks = set()
    if JOB_FUNNEL:
        return toks
    try:
        for fn in os.listdir(APPLIED_DIR):
            for rx in _APPLIED_REGEXES:
                m = rx.match(fn)
                if m:
                    tok = _norm(m.group(1))
                    if tok and tok not in EXCLUDE_STOPWORDS:
                        toks.add(tok)
                    break
    except Exception:
        pass
    toks.update(MANUAL_APPLIED)
    return toks


def is_applied(company, toks):
    c = _norm(company)
    return bool(c) and any(len(t) >= 4 and (t in c or c in t) for t in toks)


def strip_html(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def extract_hourly_rate(text):
    """Best-effort $NN/hr or $NN-NN/hour rate, for contract postings that quote
    hourly instead of annual (rare in disclosed form, but worth catching)."""
    if not text:
        return None
    vals = [int(m) for m in re.findall(
        r"\$\s?(\d{2,3})(?:\.\d+)?\s?(?:/\s?(?:hr|hour)\b|per\s?hour\b)", text, re.I)]
    plausible = [v for v in vals if 25 <= v <= 400]
    return max(plausible) if plausible else None


def extract_salary(text):
    if not text:
        return None
    # Strip "401k"/"401(k)" retirement-plan mentions first -- the bare-digit
    # k-suffix pattern below would otherwise misread it as a $401,000 salary
    # (confirmed: this was silently corrupting salary data on nearly every
    # posting that mentions 401k matching, since almost none of them are
    # preceded by a $ sign the way a real salary figure would be).
    text = re.sub(r"401\s?\(?[kK]\)?\b", "", text)
    t = text.replace(",", "")
    vals = [int(m) for m in re.findall(r"\$\s?(\d{5,7})\b", t)]
    vals += [int(m) * 1000 for m in re.findall(r"\$\s?(\d{2,3})\s?[kK]\b", text)]
    # Fold a disclosed hourly rate in as its annualized equivalent (2080 hrs/yr)
    # so contract postings still clear the same salary-floor plumbing FT
    # postings use in prefilter.py -- the raw hourly figure is kept separately
    # in rec()'s "rate_hourly" for the judge step, since annualizing overstates
    # a 1099 rate (no benefits, no PTO, SE tax) and shouldn't be shown as if
    # it were a comparable salary without that caveat.
    hourly = extract_hourly_rate(text)
    if hourly:
        vals.append(hourly * 2080)
    plausible = [v for v in vals if 50_000 <= v <= 1_000_000]
    return max(plausible) if plausible else None


def coarse_match(title, blob, mode="fulltime", title_only=False):
    """title_only: contract mode on company ATS feeds (Greenhouse/Ashby/Lever)
    only. Live-tested 2026-09-23: matching CONTRACT_TERMS against the full
    body on these feeds was 267/268 false positives -- nearly every FT
    posting's EEO/privacy-policy footer mentions "contractor" (e.g. a link
    titled ".../Employee-and-Contractor-Privacy-Policy.pdf") or "temporary"
    (work authorization boilerplate), which swamped the few genuine hits.
    Employer-written titles don't carry that boilerplate, so title-only
    matching is used there. Board/aggregator sources (RemoteOK, Remotive, WWR)
    keep body matching but with CONTRACT_BODY_TERMS, not the full list --
    bare "contract"/"contractor" in a body has its own noise problem there
    (see CONTRACT_BODY_TERMS's comment)."""
    tl = title.lower()
    if mode == "contract":
        title_hit = any(s in tl for s in CONTRACT_TITLE_TERMS)
        if title_only:
            marker_hit = title_hit
        else:
            marker_hit = title_hit or any(s in blob.lower() for s in CONTRACT_BODY_TERMS)
    else:
        marker_hit = any(s in tl for s in SENIORITY)
    return (marker_hit
            and any(r in tl for r in ROLE)
            and any(k in blob.lower() for k in TECH))


def us_remote(text):
    t = (text or "").lower()
    return any(h in t for h in US_HINTS)


def to_date(v):
    """A feed's date as YYYY-MM-DD, or None. Accepts ISO 8601 strings, RFC 822
    (RSS pubDate) strings, and epoch seconds or milliseconds."""
    if v in (None, ""):
        return None
    try:
        if isinstance(v, (int, float)):
            ts = v / 1000 if v > 1e11 else v
            return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).date().isoformat()
        v = str(v).strip()
        if re.match(r"^\d{4}-\d{2}-\d{2}", v):
            return v[:10]
        return email.utils.parsedate_to_datetime(v).date().isoformat()
    except Exception:
        return None


def age_days(d):
    if not d:
        return None
    try:
        return (datetime.date.today() - datetime.date.fromisoformat(d)).days
    except ValueError:
        return None


# Stack terms looked for in a posting's full description, before it is cut to SNIPPET_LEN.
# The snippet is usually the company intro, so without this the judge can't see the stack
# without fetching every JD. A mention, not a split: "vue" + "react" means both are named.
STACK_TERMS = {
    "vue": r"\bvue(?:\.?js)?\b|\bnuxt",
    "angular": r"\bangular(?:js)?\b",
    "react": r"\breact(?:\.?js)?\b|\bnext\.js\b",
    "svelte": r"\bsvelte(?:kit)?\b",
    "typescript": r"\btypescript\b",
    "node": r"\bnode(?:\.?js)?\b",
    "dotnet": r"\.net\b|\bc#|\basp\.net\b",
    "java": r"\bjava\b(?!script)|\bspring boot\b|\bkotlin\b",
    "python": r"\bpython\b|\bdjango\b|\bfastapi\b",
    "go": r"\b[Gg]olang\b|\bGo\b(?= *(?:,|/|and|or|\)|services|microservices))",
    "ruby": r"\bruby\b|\brails\b",
    "php": r"\bphp\b|\blaravel\b",
}
# "Go" is matched case-sensitively, since "go" is also an ordinary English word.
_STACK_RX = {k: re.compile(v, 0 if k == "go" else re.I) for k, v in STACK_TERMS.items()}


def stack_of(text):
    return [k for k, rx in _STACK_RX.items() if rx.search(text)]


def rec(title, company, desc, url, source, location, salary_text="", job_type="",
        posted=None, updated=None):
    """posted/updated are the feed's own dates (first published, last updated),
    kept so the judge step scores freshness from data, not guesses. A posting
    whose updated date is well after its posted date may be a repost."""
    blob = (salary_text or "") + " " + desc
    posted, updated = to_date(posted), to_date(updated)
    return {
        "title": title, "company": company,
        "salary": extract_salary(blob),
        "rate_hourly": extract_hourly_rate(blob),
        "job_type": job_type or "",
        "location": location or "Remote",
        "us": us_remote((location or "") + " " + desc[:400]),
        "url": url, "source": source,
        "posted": posted, "updated": updated, "age_days": age_days(posted),
        "stack": stack_of(title + " " + strip_html(desc)),
        "snippet": strip_html(desc)[:SNIPPET_LEN],
    }


# ------------------------------ sources -------------------------------------
def from_remoteok(mode="fulltime"):
    out = []
    try:
        data = json.loads(get("https://remoteok.com/api"))[1:]
    except Exception as e:
        _failed("RemoteOK", "remoteok", e)
        return out
    for j in data:
        title = j.get("position", "")
        tags = j.get("tags", [])
        # RemoteOK has no explicit job-type field; "freelance" is the closest
        # tag signal it exposes, folded into coarse_match's text search below
        # via the tag join -- not filtered separately.
        blob = strip_html(j.get("description", "")) + " " + " ".join(tags)
        if coarse_match(title, blob, mode):
            out.append(rec(title, j.get("company", ""), blob,
                           j.get("url") or j.get("apply_url", ""), "RemoteOK",
                           j.get("location") or "Remote",
                           posted=j.get("date") or j.get("epoch")))
    return out


def from_remotive(mode="fulltime"):
    out = []
    try:
        data = json.loads(get("https://remotive.com/api/remote-jobs?category=software-dev&limit=100"))
    except Exception as e:
        _failed("Remotive", "remotive", e)
        return out
    for j in data.get("jobs", []):
        jt = (j.get("job_type") or "").lower()
        # Remotive discloses job_type directly -- use it as a hard filter on
        # top of the text match rather than relying on keywords alone, since
        # it's ground truth where the coarse text search is a guess.
        if mode == "contract" and jt not in ("contract", "freelance", "temporary", ""):
            continue
        if mode == "fulltime" and jt not in ("full_time", ""):
            continue
        title = j.get("title", "")
        blob = strip_html(j.get("description", "")) + " " + " ".join(j.get("tags", []))
        if coarse_match(title, blob, mode):
            out.append(rec(title, j.get("company_name", ""), blob, j.get("url", ""),
                           "Remotive", j.get("candidate_required_location", ""),
                           j.get("salary", ""), job_type=jt,
                           posted=j.get("publication_date")))
    return out


def from_wwr(mode="contract"):
    """We Work Remotely RSS -- agencies and marketplaces post contract reqs
    here heavily, and it has no public JSON API, just RSS. Titles are
    "Company: Position"; split on the first colon."""
    out = []
    for feed_url in WWR_FEEDS:
        try:
            xml_text = get(feed_url)
            root = ET.fromstring(xml_text)
        except Exception as e:
            _failed("WWR", feed_url.rsplit("/", 1)[-1], e)
            continue
        for item in root.findall(".//item"):
            raw_title = (item.findtext("title") or "").strip()
            company, _, title = raw_title.partition(":")
            title = title.strip() or raw_title
            company = company.strip() if _ else ""
            desc = strip_html(item.findtext("description") or "")
            region = item.findtext("region") or ""
            link = item.findtext("link") or ""
            if coarse_match(title, desc, mode):
                out.append(rec(title, company or "Unknown", desc, link,
                               "WeWorkRemotely", region,
                               posted=item.findtext("pubDate")))
    return out


def from_himalayas(mode="contract"):
    """Himalayas.app public search API -- no auth key, and unlike RemoteOK/
    Remotive/WWR it takes employment_type + country as real server-side
    filters rather than relying on us to infer them from text. That server
    filter is layered ON TOP of coarse_match (same pattern as Remotive's
    job_type check above), not a replacement for it -- still requires the
    usual ROLE/TECH text signal in title+description.
    Contract-only: fulltime mode has no server-side employment_type value
    that cleanly maps (Himalayas' "Full-time" tier includes plenty of non-US
    remote-anywhere postings we'd rather leave to the existing FT sources)."""
    if mode != "contract":
        return []
    out, seen = [], set()
    for q in HIMALAYAS_QUERIES:
        url = ("https://himalayas.app/jobs/api/search?" + urllib.parse.urlencode({
            "q": q, "employment_type": "Contractor", "country": "US",
            "sort": "recent", "limit": 20,
        }))
        try:
            data = json.loads(get(url))
        except Exception as e:
            _failed("Himalayas", q, e)
            continue
        for j in data.get("jobs", []):
            guid = j.get("guid") or j.get("applicationLink") or ""
            if not guid or guid in seen:
                continue
            seen.add(guid)
            title = j.get("title", "")
            desc = strip_html(j.get("description") or j.get("excerpt") or "")
            mn, mx = j.get("minSalary"), j.get("maxSalary")
            period = (j.get("salaryPeriod") or "annual").lower()
            salary_text = ""
            if mn or mx:
                val = mx or mn
                salary_text = f"${val}/hr" if period == "hourly" else f"${val}"
            if coarse_match(title, desc, mode):
                out.append(rec(title, j.get("companyName", ""), desc,
                               j.get("applicationLink", ""), "Himalayas",
                               "Remote (US eligible)", salary_text,
                               posted=j.get("pubDate")))
    return out


def from_greenhouse(token, mode="fulltime"):
    out = []
    try:
        data = json.loads(get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"))
    except Exception as e:
        _failed("Greenhouse", token, e)
        return out
    for j in data.get("jobs", []):
        title = j.get("title", "")
        loc = (j.get("location") or {}).get("name") or ""
        content = strip_html(urllib.parse.unquote(j.get("content", "")))
        if "remote" in (loc + " " + content).lower() and coarse_match(title, content, mode, title_only=(mode == "contract")):
            out.append(rec(title, COMPANY_NAMES.get(token, token.title()), content, j.get("absolute_url", ""),
                           "Greenhouse", loc,
                           posted=j.get("first_published"), updated=j.get("updated_at")))
    return out


def from_ashby(name, mode="fulltime"):
    out = []
    try:
        data = json.loads(get("https://api.ashbyhq.com/posting-api/job-board/"
                              + urllib.parse.quote(name) + "?includeCompensation=true"))
    except Exception as e:
        _failed("Ashby", name, e)
        return out
    for j in data.get("jobs", []):
        title = j.get("title", "")
        loc = j.get("location") or ""
        if not (j.get("isRemote") or "remote" in loc.lower()):
            continue
        desc = j.get("descriptionPlain") or strip_html(j.get("descriptionHtml", ""))
        if coarse_match(title, desc, mode, title_only=(mode == "contract")):
            out.append(rec(title, COMPANY_NAMES.get(name, name), desc, j.get("applyUrl") or j.get("jobUrl", ""),
                           "Ashby", loc, json.dumps(j.get("compensation") or {}),
                           posted=j.get("publishedAt"), updated=j.get("updatedAt")))
    return out


def from_lever(token, mode="fulltime"):
    out = []
    try:
        data = json.loads(get(f"https://api.lever.co/v0/postings/{token}?mode=json"))
    except Exception as e:
        _failed("Lever", token, e)
        return out
    for j in data:
        title = j.get("text", "")
        cats = j.get("categories") or {}
        loc = cats.get("location") or ""
        desc = j.get("descriptionPlain", "")
        if "remote" in (loc + " " + desc).lower() and coarse_match(title, desc, mode, title_only=(mode == "contract")):
            out.append(rec(title, COMPANY_NAMES.get(token, token.title()), desc, j.get("hostedUrl", ""),
                           "Lever", loc, json.dumps(j.get("salaryRange") or {}),
                           posted=j.get("createdAt"), updated=j.get("updatedAt")))
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["fulltime", "contract"], default="fulltime",
                         help="fulltime (default, unchanged behavior) or contract "
                              "(relaxes seniority, requires contract/1099 language, "
                              "adds We Work Remotely)")
    args = parser.parse_args()
    mode = args.mode

    jobs = []
    with ThreadPoolExecutor(max_workers=32) as ex:
        futs = {ex.submit(from_remoteok, mode): ("RemoteOK", "remoteok"),
                ex.submit(from_remotive, mode): ("Remotive", "remotive")}
        futs.update({ex.submit(from_greenhouse, t, mode): ("Greenhouse", t) for t in GREENHOUSE})
        futs.update({ex.submit(from_ashby, n, mode): ("Ashby", n) for n in ASHBY})
        futs.update({ex.submit(from_lever, t, mode): ("Lever", t) for t in LEVER})
        if mode == "contract":
            futs[ex.submit(from_wwr, mode)] = ("WWR", "wwr")
            futs[ex.submit(from_himalayas, mode)] = ("Himalayas", "himalayas")
        for f in as_completed(futs):
            try:
                jobs.extend(f.result())
            except Exception as e:  # a fetcher crashed after its fetch, e.g. on an unexpected shape
                _failed(*futs[f], e)

    seen, uniq = set(), []
    for j in jobs:
        k = (j["company"].lower(), j["title"].lower())
        if k not in seen:
            seen.add(k)
            uniq.append(j)

    # drop companies already applied to (tailored docs on disk)
    toks = applied_tokens()
    excluded = sorted({j["company"] for j in uniq if is_applied(j["company"], toks)})
    uniq = [j for j in uniq if not is_applied(j["company"], toks)]
    uniq.sort(key=lambda x: (-(x["salary"] or 0), x["company"]))

    out_name = "job_candidates.json" if mode == "fulltime" else "job_candidates_contract.json"
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), out_name)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(uniq, fh, indent=2)

    by_src = {}
    for j in uniq:
        by_src[j["source"]] = by_src.get(j["source"], 0) + 1
    print(f"[{mode}] Gathered {len(uniq)} coarse-matched candidates (after exclusions) by source: {by_src}")
    print(f"With disclosed salary/rate: {sum(1 for j in uniq if j['salary'])}")
    print(f"Excluded (already applied): {', '.join(excluded) if excluded else 'none'}")
    failed = sorted(FAILED_FEEDS)
    print(f"Unreachable feeds ({len(failed)}): "
          + (", ".join(f"{src} {name} ({why})" for src, name, why in failed) if failed else "none"))
    print(f"JSON written to: {out_path}")
    print(f"Next: Claude reads {out_name} and judges fit per record.")


if __name__ == "__main__":
    main()
