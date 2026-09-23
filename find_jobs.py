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
    contract reqs there heavily) and filters Remotive/RemoteOK by their native
    job-type/tag fields in addition to text. Writes job_candidates_contract.json
    so a contract gather never clobbers a fulltime one (and vice versa).

Output: writes the mode's JSON file (full records w/ snippets) next to this
script and prints a short summary. No third-party deps (urllib + stdlib xml only).
Edit CONFIG to tune criteria or add companies (unknown ATS tokens are skipped).

Not covered here: pure W-2 staffing agencies (Kforce, TEKsystems, Insight
Global, Robert Half, Dexian) and vetted marketplaces (Braintrust, Toptal).
None expose a public feed — Braintrust's own job list is gated behind
"Certified Talent" membership, not a public board. Those are a manual
registration/application step, not something this script can gather.
"""

import argparse
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
TECH = ["vue", "react", "typescript", "javascript", "full stack", "fullstack",
        "full-stack", "front-end", "frontend", "node", "python"]
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
WWR_FEEDS = [
    "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-front-end-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
]

GREENHOUSE = [
    # --- original ---
    "stripe", "airbnb", "reddit", "brex", "ramp", "gusto", "benchling",
    "discord", "robinhood", "coinbase", "databricks", "cloudflare",
    "twilio", "asana", "figma", "dropbox", "instacart", "affirm",
    "gitlab", "hashicorp", "shopify", "datadog", "doordash", "pinterest",
    "block", "elastic", "mongodb", "confluent", "samsara", "airtable",
    "webflow", "contentful", "sourcegraph", "postman", "grafanalabs",
    "render", "zapier", "retool", "mercury", "chime", "kraken", "okta",
    "cockroachlabs", "niantic", "roblox", "unity", "gemini", "plaid",
    # --- expanded: big tech / late-stage ---
    "netlify", "supabase", "vercel", "deno", "fly", "railway",
    "launchdarkly", "stytch", "axiom", "posthog", "planetscale",
    "neon", "turso", "upstash", "convex", "clerk", "inngest",
    "temporal", "prefect", "dagster", "modal", "anyscale", "replicate",
    "huggingface", "anthropic", "openai", "mistral",
    # --- fintech / payments ---
    "marqeta", "toast", "adyen", "wise", "remitly", "melio",
    "bill", "rippling", "justworks", "paylocity", "carta",
    "braintree", "lithic", "moderntreasury", "column", "increase",
    "unit", "treasuryprime", "synctera", "bond", "highnote",
    # --- B2B SaaS / productivity ---
    "notion", "coda", "clickup", "linear", "height", "shortcut",
    "loom", "miro", "mural", "canva", "grammarly", "calendly",
    "typeform", "airtable", "smartsheet", "monday", "lattice",
    "rippling", "gusto", "deel", "remote", "oysterhr", "justworks",
    "greenhouse", "lever", "ashbyhq", "gem", "dover",
    # --- developer tools / infra ---
    "hashicorp", "snyk", "sonar", "sentry", "circleci", "buildkite",
    "pulumi", "env0", "spacelift", "firehydrant", "rootly", "blameless",
    "pagerduty", "opsgenie", "squadcast", "honeycomb", "lightstep",
    "chronosphere", "cribl", "mezmo", "logdna", "coralogix",
    "launchdarkly", "split", "statsig", "eppo", "growthbook",
    "stytch", "workos", "fusionauth", "descope", "authzed",
    "zesty", "vantage", "cloudhealth", "spot", "cast",
    # --- data / analytics ---
    "dbt-labs", "fivetran", "airbyte", "census", "hightouch",
    "hex", "mode", "sigma", "lightdash", "cube", "metabase",
    "preset", "atlan", "alation", "collibra", "immuta",
    "snowflake", "motherduck", "clickhouse", "timescale", "questdb",
    # --- security ---
    "crowdstrike", "sentinelone", "lacework", "orca", "wiz",
    "snyk", "veracode", "checkmarx", "semgrep", "endor",
    "bitwarden", "1password", "dashlane", "keeper",
    # --- AI / ML companies ---
    "scale", "labelbox", "weights-and-biases", "mlflow",
    "pinecone", "weaviate", "qdrant", "chroma", "zilliz",
    "langchain", "llamaindex", "fixie", "dust", "vellum",
    "jasper", "writer", "copy-ai", "runway", "stability",
    "midjourney", "elevenelabs", "assemblyai", "deepgram",
    "glean", "moveworks", "adept", "cognition", "poolside",
    # --- e-commerce / marketplace ---
    "etsy", "poshmark", "mercari", "offerup", "depop",
    "faire", "shein", "fanatics", "goat", "stockx",
    "shipbob", "shippo", "easypost", "narvar",
    # --- health tech ---
    "oscar", "devoted", "cityblock", "ro", "hims",
    "truepill", "capsule", "alto", "amazon-pharmacy",
    "flatiron", "tempus", "veracyte", "grail",
    # --- education ---
    "duolingo", "coursera", "udemy", "masterclass", "khan",
    "replit", "codecademy", "brilliant",
    # --- misc remote-friendly ---
    "automattic", "zapier", "buffer", "doist", "toggl",
    "hotjar", "convertkit", "transistor", "fathom",
    "fly", "render", "railway", "coolify",
    "planetscale", "neon", "xata", "turso",
    "expo", "eas", "tamagui", "nativewind",
]
ASHBY = [
    # --- original ---
    "Gray Swan AI", "Linear", "Vercel", "Replit",
    "Retool", "Mercury", "Perplexity AI", "Cursor", "Cohere", "Notion", "Deel",
    # --- expanded ---
    "Ramp", "Anthropic", "OpenAI", "Mistral AI", "Anduril",
    "Supabase", "PostHog", "Deno", "Clerk", "Convex",
    "Inngest", "Axiom", "Neon", "Turso", "Upstash",
    "Fly.io", "Railway", "Render", "Coolify",
    "Stytch", "WorkOS", "Descope", "AuthZed",
    "Warp", "Fig", "Zed", "GitButler",
    "Temporal", "Prefect", "Dagster", "Modal",
    "Dust", "Vellum", "LangChain", "LlamaIndex",
    "Glean", "Harvey", "Casetext", "EvenUp",
    "Weights & Biases", "Pinecone", "Weaviate", "Chroma",
    "AssemblyAI", "Deepgram", "ElevenLabs", "Stability AI",
    "Scale AI", "Labelbox", "Replicate", "Together AI",
    "Braintrust", "Humanloop", "Helicone", "Langfuse",
    "Resend", "Loops", "Svix", "Knock", "Novu",
    "Cal.com", "Formbricks", "Documenso", "Eraser",
    "Doppler", "Infisical", "GitGuardian",
    "Secureframe", "Drata", "Vanta", "Launchnotes",
    "Hightouch", "Census", "Rudderstack", "Segment",
    "Hex", "Sigma Computing", "Lightdash", "Cube",
    "Atlan", "Monte Carlo", "Bigeye", "Metaplane",
    "Flatfile", "OneSchema", "Osmos",
    "Plain", "Intercom", "Front", "Missive",
    "Stripe", "Plaid", "Unit", "Lithic", "Increase",
    "Modern Treasury", "Column", "Synctera", "Highnote",
    "Carta", "Pulley", "AngelList", "Wellfound",
    "Remote", "Oyster", "Deel", "Plane",
    "Lattice", "Culture Amp", "15Five", "Leapsome",
    "Ashby", "Gem", "Dover", "Greenhouse",
    "Liveblocks", "Tldraw", "Excalidraw",
    "Trigger.dev", "Defer", "Qstash",
    "Mintlify", "ReadMe", "Stoplight", "Bump.sh",
    "Grafbase", "Hasura", "Stellate", "WunderGraph",
    "EdgeDB", "SurrealDB", "CockroachDB",
    "PlanetScale", "Xata", "Fauna",
]
LEVER = [
    # --- original ---
    "veeva", "plaid", "netflix", "nerdwallet", "attentive", "gopuff",
    # --- expanded ---
    "netlify", "sanity", "contentful", "strapi", "storyblok",
    "algolia", "typesense", "meilisearch",
    "auth0", "okta", "onelogin",
    "twilio", "sendgrid", "messagebird", "vonage",
    "segment", "amplitude", "mixpanel", "heap", "fullstory",
    "launchdarkly", "split", "statsig", "optimizely",
    "fastly", "akamai", "bunny",
    "circleci", "semaphore", "harness", "codefresh",
    "sonarqube", "codeclimate", "deepsource",
    "snyk", "bridgecrew", "checkov",
    "tailscale", "twingate", "zscaler",
    "loom", "pitch", "gamma", "beautiful",
    "calendly", "savvycal", "reclaim",
    "linear", "shortcut", "clickup", "height",
    "notion", "coda", "slite",
    "figma", "framer", "webflow", "bubble",
    "retool", "internal", "appsmith", "tooljet",
    "supabase", "firebase", "convex",
    "prisma", "drizzle", "kysely",
    "vercel", "netlify", "render", "railway",
    "fly", "modal", "replicate", "banana",
    "weights-and-biases", "comet", "neptune",
    "huggingface", "roboflow", "labelbox",
    "jasper", "writer", "copy-ai", "anyword",
    "grammarly", "textio", "hemingway",
    "wise", "remitly", "airwallex", "payoneer",
    "marqeta", "lithic", "highnote", "unit",
    "brex", "divvy", "ramp", "airbase",
    "toast", "square", "clover", "lightspeed",
    "shopify", "bigcommerce", "swell", "medusa",
    "faire", "handshake", "firstbase",
    "calm", "headspace", "noom", "peloton",
    "duolingo", "coursera", "udemy", "skillshare",
    "automattic", "ghost", "substack", "beehiiv",
    "doist", "todoist", "toggl", "clockify",
    "buffer", "hootsuite", "sprout", "later",
    "hotjar", "smartlook", "mouseflow", "clarity",
    "convertkit", "mailchimp", "customer-io", "braze",
    "intercom", "zendesk", "freshworks", "helpscout",
    "pagerduty", "opsgenie", "betteruptime",
    "sentry", "bugsnag", "rollbar", "raygun",
    "datadog", "newrelic", "dynatrace", "elastic",
    "hashicorp", "pulumi", "crossplane", "env0",
    "terraform", "spacelift", "scalr",
    "docker", "rancher", "portainer",
    "gitpod", "codespaces", "coder", "devpod",
    "doppler", "infisical", "vault",
    "tailscale", "ngrok", "cloudflared",
]

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept": "application/json,text/plain,*/*"}
TIMEOUT = 20
RETRIES = 3                # retry transient failures / rate limits with backoff
# Companies manually marked as already applied (add your own)
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


_resume_cfg = _load_local_config().get("resume", {})
# Directory scanned to auto-exclude companies already applied to (tailored docs present).
# From config.json's resume.applied_docs_dir; empty disables the auto-exclusion.
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
    """Company tokens from tailored docs in APPLIED_DIR, to skip already-applied roles."""
    toks = set()
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
    matching is used there. Board/aggregator sources (RemoteOK, Remotive,
    WWR) don't have this problem to the same degree and keep body matching."""
    tl = title.lower()
    if mode == "contract":
        title_hit = any(s in tl for s in CONTRACT_TITLE_TERMS)
        if title_only:
            marker_hit = title_hit
        else:
            marker_hit = title_hit or any(s in blob.lower() for s in CONTRACT_TERMS)
    else:
        marker_hit = any(s in tl for s in SENIORITY)
    return (marker_hit
            and any(r in tl for r in ROLE)
            and any(k in blob.lower() for k in TECH))


def us_remote(text):
    t = (text or "").lower()
    return any(h in t for h in US_HINTS)


def rec(title, company, desc, url, source, location, salary_text="", job_type=""):
    blob = (salary_text or "") + " " + desc
    return {
        "title": title, "company": company,
        "salary": extract_salary(blob),
        "rate_hourly": extract_hourly_rate(blob),
        "job_type": job_type or "",
        "location": location or "Remote",
        "us": us_remote((location or "") + " " + desc[:400]),
        "url": url, "source": source,
        "snippet": strip_html(desc)[:SNIPPET_LEN],
    }


# ------------------------------ sources -------------------------------------
def from_remoteok(mode="fulltime"):
    out = []
    try:
        data = json.loads(get("https://remoteok.com/api"))[1:]
    except Exception:
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
                           j.get("location") or "Remote"))
    return out


def from_remotive(mode="fulltime"):
    out = []
    try:
        data = json.loads(get("https://remotive.com/api/remote-jobs?category=software-dev&limit=100"))
    except Exception:
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
                           j.get("salary", ""), job_type=jt))
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
        except Exception:
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
                               "WeWorkRemotely", region))
    return out


def from_greenhouse(token, mode="fulltime"):
    out = []
    try:
        data = json.loads(get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"))
    except Exception:
        return out
    for j in data.get("jobs", []):
        title = j.get("title", "")
        loc = (j.get("location") or {}).get("name", "")
        content = strip_html(urllib.parse.unquote(j.get("content", "")))
        if "remote" in (loc + " " + content).lower() and coarse_match(title, content, mode, title_only=(mode == "contract")):
            out.append(rec(title, token.title(), content, j.get("absolute_url", ""),
                           "Greenhouse", loc))
    return out


def from_ashby(name, mode="fulltime"):
    out = []
    try:
        data = json.loads(get("https://api.ashbyhq.com/posting-api/job-board/"
                              + urllib.parse.quote(name) + "?includeCompensation=true"))
    except Exception:
        return out
    for j in data.get("jobs", []):
        title = j.get("title", "")
        loc = j.get("location") or ""
        if not (j.get("isRemote") or "remote" in loc.lower()):
            continue
        desc = j.get("descriptionPlain") or strip_html(j.get("descriptionHtml", ""))
        if coarse_match(title, desc, mode, title_only=(mode == "contract")):
            out.append(rec(title, name, desc, j.get("applyUrl") or j.get("jobUrl", ""),
                           "Ashby", loc, json.dumps(j.get("compensation") or {})))
    return out


def from_lever(token, mode="fulltime"):
    out = []
    try:
        data = json.loads(get(f"https://api.lever.co/v0/postings/{token}?mode=json"))
    except Exception:
        return out
    for j in data:
        title = j.get("text", "")
        cats = j.get("categories") or {}
        loc = cats.get("location", "")
        desc = j.get("descriptionPlain", "")
        if "remote" in (loc + " " + desc).lower() and coarse_match(title, desc, mode, title_only=(mode == "contract")):
            out.append(rec(title, token.title(), desc, j.get("hostedUrl", ""),
                           "Lever", loc, json.dumps(j.get("salaryRange") or {})))
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
        futs = [ex.submit(from_remoteok, mode), ex.submit(from_remotive, mode)]
        futs += [ex.submit(from_greenhouse, t, mode) for t in GREENHOUSE]
        futs += [ex.submit(from_ashby, n, mode) for n in ASHBY]
        futs += [ex.submit(from_lever, t, mode) for t in LEVER]
        if mode == "contract":
            futs.append(ex.submit(from_wwr, mode))
        for f in as_completed(futs):
            try:
                jobs.extend(f.result())
            except Exception:
                pass

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
    print(f"JSON written to: {out_path}")
    print(f"Next: Claude reads {out_name} and judges fit per record.")


if __name__ == "__main__":
    main()
