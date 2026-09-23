"""
Generate a tailored resume and cover letter from JSON input.

Always writes Markdown (the source of truth — readable, diffable, easy to
tweak by hand). Pass --pdf to also render a PDF for submission, via a
headless Chrome print (macOS, zero extra installs).

Usage:
    python generate_resume_cover.py --config /path/to/config.json [--pdf]

Config (config.json):
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

Reads (from output_dir):
    - resume_tailored.json
    - cover_letter_tailored.json

Writes (to output_dir):
    - {Name}_Resume_{company}_{title}.md
    - {Name}_CoverLetter_{company}_{title}.md
    - (with --pdf) matching .pdf files, rendered via headless Chrome

JSON Schemas
============

resume_tailored.json:
{
    "company": "Acme Corp",
    "short_title": "Staff_FE",
    "summary": "Full text of professional summary...",
    "jobs": [
        {
            "title": "Lead Software Engineer",
            "company_line": "Company Name  |  Mar 2023 - Present  |  City, ST (Remote)",
            "bullets": [
                "Bullet point text...",
                "Another bullet..."
            ]
        }
    ],
    "education": [
        "Bachelor of Science, Computer Science -- University Name  |  2010 - 2014"
    ],
    "skills": [
        {"label": "Frontend", "value": "JavaScript, TypeScript, React..."},
        {"label": "Backend", "value": "Python, Node.js..."},
        {"label": "Tools", "value": "Git, Docker..."}
    ]
}

cover_letter_tailored.json:
{
    "company": "Acme Corp",
    "short_title": "Staff_FE",
    "recipient": "Dear Acme Corp Hiring Team,",
    "opening": "Opening paragraph text...",
    "body_sections": [
        {
            "bold_lead": "Frontend platform leadership at scale. ",
            "text": "Rest of the paragraph..."
        }
    ],
    "closing": "Closing paragraph text...",
    "signoff": "Thank you for your consideration."
}
"""

import argparse
import html
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]

PAGE_CSS = """
body { font-family: Calibri, "Helvetica Neue", Arial, sans-serif; color: #1a1a1a;
       font-size: 11pt; margin: 0.6in 0.7in; }
h1 { text-align: center; font-size: 20pt; margin: 0 0 2pt 0; }
.contact { text-align: center; font-size: 10pt; margin: 0 0 2pt 0; color: #333; }
hr { border: none; border-top: 1px solid #b4b4b4; margin: 6pt 0; }
h2 { font-size: 12pt; margin: 10pt 0 3pt 0; }
p { margin: 0 0 4pt 0; }
.job-title { font-weight: bold; font-size: 11pt; margin: 6pt 0 0 0; }
.company-line { font-size: 10pt; color: #646464; margin: 0 0 2pt 0; }
ul { margin: 0 0 4pt 0; padding-left: 18pt; }
li { font-size: 10pt; margin: 1pt 0; }
.skill-label { font-weight: bold; }
"""

COVER_CSS = """
body { font-family: Calibri, "Helvetica Neue", Arial, sans-serif; color: #1a1a1a;
       font-size: 11pt; margin: 1in; }
.name { font-weight: bold; font-size: 14pt; margin: 0; }
.line { margin: 0 0 2pt 0; }
.greeting { margin: 16pt 0 8pt 0; }
.lead { font-weight: bold; }
p { margin: 0 0 8pt 0; }
"""


def load_config(config_path):
    with open(config_path, encoding="utf-8") as f:
        cfg = json.load(f)
    required = ["name", "email", "output_dir"]
    for key in required:
        if key not in cfg:
            print(f"ERROR: config.json missing required key: {key}", file=sys.stderr)
            sys.exit(1)
    return cfg


def esc(text):
    return html.escape(text, quote=False)


# -- Resume --------------------------------------------------------------


def build_resume_markdown(data, cfg):
    lines = [f"# {cfg['name']}", ""]

    contact1 = [p for p in [cfg.get("location"), cfg.get("linkedin"), cfg.get("website")] if p]
    if contact1:
        lines.append(" | ".join(contact1))
    contact2 = [p for p in [cfg.get("email"), cfg.get("phone")] if p]
    if contact2:
        lines.append(" | ".join(contact2))
    lines += ["", "---", "", "## Professional Summary", "", data["summary"], "", "---", "",
              "## Professional Experience", ""]

    for job in data["jobs"]:
        lines.append(f"**{job['title']}**")
        lines.append(f"*{job['company_line']}*")
        lines.append("")
        for b in job["bullets"]:
            lines.append(f"- {b}")
        lines.append("")

    lines += ["---", "", "## Education", ""]
    for edu in data["education"]:
        lines.append(f"- {edu}")

    lines += ["", "---", "", "## Technical Skills", ""]
    for skill in data["skills"]:
        lines.append(f"- **{skill['label']}:** {skill['value']}")

    return "\n".join(lines) + "\n"


def build_resume_html(data, cfg):
    parts = [f"<html><head><meta charset='utf-8'><style>{PAGE_CSS}</style></head><body>"]
    parts.append(f"<h1>{esc(cfg['name'])}</h1>")

    contact1 = [esc(p) for p in [cfg.get("location"), cfg.get("linkedin"), cfg.get("website")] if p]
    if contact1:
        parts.append(f"<p class='contact'>{'&nbsp;&nbsp;|&nbsp;&nbsp;'.join(contact1)}</p>")
    contact2 = [esc(p) for p in [cfg.get("email"), cfg.get("phone")] if p]
    if contact2:
        parts.append(f"<p class='contact'>{'&nbsp;&nbsp;|&nbsp;&nbsp;'.join(contact2)}</p>")

    parts.append("<hr><h2>Professional Summary</h2>")
    parts.append(f"<p>{esc(data['summary'])}</p>")

    parts.append("<hr><h2>Professional Experience</h2>")
    for job in data["jobs"]:
        parts.append(f"<p class='job-title'>{esc(job['title'])}</p>")
        parts.append(f"<p class='company-line'>{esc(job['company_line'])}</p>")
        parts.append("<ul>" + "".join(f"<li>{esc(b)}</li>" for b in job["bullets"]) + "</ul>")

    parts.append("<hr><h2>Education</h2><ul>")
    parts += [f"<li>{esc(e)}</li>" for e in data["education"]]
    parts.append("</ul>")

    parts.append("<hr><h2>Technical Skills</h2><ul>")
    for skill in data["skills"]:
        parts.append(f"<li><span class='skill-label'>{esc(skill['label'])}:</span> {esc(skill['value'])}</li>")
    parts.append("</ul></body></html>")

    return "\n".join(parts)


# -- Cover Letter ----------------------------------------------------------


def build_cover_markdown(data, cfg):
    lines = [f"**{cfg['name']}**"]
    if cfg.get("location"):
        lines.append(cfg["location"])
    contact = [p for p in [cfg.get("email"), cfg.get("phone")] if p]
    if contact:
        lines.append(" | ".join(contact))
    links = [p for p in [cfg.get("website"), cfg.get("linkedin"), cfg.get("github")] if p]
    if links:
        lines.append(" | ".join(links))
    lines.append("")

    lines += [data["recipient"], "", data["opening"], ""]

    for sec in data["body_sections"]:
        lines.append(f"**{sec['bold_lead']}**{sec['text']}")
        lines.append("")

    lines += [data["closing"], "", data["signoff"], "", "Sincerely,", "", f"**{cfg['name']}**"]
    return "\n".join(lines) + "\n"


def build_cover_html(data, cfg):
    parts = [f"<html><head><meta charset='utf-8'><style>{COVER_CSS}</style></head><body>"]
    parts.append(f"<p class='name'>{esc(cfg['name'])}</p>")
    if cfg.get("location"):
        parts.append(f"<p class='line'>{esc(cfg['location'])}</p>")
    contact = [esc(p) for p in [cfg.get("email"), cfg.get("phone")] if p]
    if contact:
        parts.append(f"<p class='line'>{'&nbsp;&nbsp;|&nbsp;&nbsp;'.join(contact)}</p>")
    links = [esc(p) for p in [cfg.get("website"), cfg.get("linkedin"), cfg.get("github")] if p]
    if links:
        parts.append(f"<p class='line'>{'&nbsp;&nbsp;|&nbsp;&nbsp;'.join(links)}</p>")

    parts.append(f"<p class='greeting'>{esc(data['recipient'])}</p>")
    parts.append(f"<p>{esc(data['opening'])}</p>")

    for sec in data["body_sections"]:
        parts.append(f"<p><span class='lead'>{esc(sec['bold_lead'])}</span>{esc(sec['text'])}</p>")

    parts.append(f"<p>{esc(data['closing'])}</p>")
    parts.append(f"<p>{esc(data['signoff'])}</p>")
    parts.append("<p>Sincerely,</p>")
    parts.append(f"<p><strong>{esc(cfg['name'])}</strong></p>")
    parts.append("</body></html>")
    return "\n".join(parts)


# -- PDF rendering -----------------------------------------------------------


def find_chrome():
    for path in CHROME_CANDIDATES:
        if Path(path).exists():
            return path
    found = shutil.which("chrome") or shutil.which("chromium")
    if found:
        return found
    return None


def render_pdf(html_str, pdf_path, chrome_path):
    with tempfile.NamedTemporaryFile(suffix=".html", mode="w", encoding="utf-8", delete=False) as f:
        f.write(html_str)
        tmp_html = f.name
    try:
        subprocess.run(
            [chrome_path, "--headless", "--disable-gpu", "--no-pdf-header-footer",
             f"--print-to-pdf={pdf_path}", f"file://{tmp_html}"],
            check=True, capture_output=True,
        )
    finally:
        Path(tmp_html).unlink(missing_ok=True)


# -- Main --------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Generate a tailored cover letter (Markdown, optionally PDF). "
                     "Resume is NOT generated unless --with-resume is passed -- "
                     "default to the user's own master resume for actual submissions.")
    parser.add_argument("--config", required=True,
                        help="Path to config.json with personal info and paths")
    parser.add_argument("--pdf", action="store_true",
                        help="Also render PDF versions via headless Chrome")
    parser.add_argument("--with-resume", action="store_true",
                        help="Also generate a tailored resume. Off by default -- "
                             "only pass this if explicitly asked for a tailored resume.")
    args = parser.parse_args()

    cfg = load_config(args.config)
    output_dir = Path(cfg["output_dir"])

    resume_json = output_dir / "resume_tailored.json"
    cover_json = output_dir / "cover_letter_tailored.json"

    if not cover_json.exists():
        print(f"ERROR: {cover_json} not found", file=sys.stderr)
        sys.exit(1)
    if args.with_resume and not resume_json.exists():
        print(f"ERROR: {resume_json} not found", file=sys.stderr)
        sys.exit(1)

    with open(cover_json, encoding="utf-8") as f:
        cover_data = json.load(f)

    company = cover_data["company"]
    short_title = cover_data["short_title"]
    safe_name = cfg["name"].replace(" ", "_")

    resume_data = None
    if args.with_resume:
        with open(resume_json, encoding="utf-8") as f:
            resume_data = json.load(f)

        resume_md = build_resume_markdown(resume_data, cfg)
        resume_md_path = output_dir / f"{safe_name}_Resume_{company}_{short_title}.md"
        resume_md_path.write_text(resume_md, encoding="utf-8")
        print(f"Resume saved: {resume_md_path}")

    cover_md = build_cover_markdown(cover_data, cfg)
    cover_md_path = output_dir / f"{safe_name}_CoverLetter_{company}_{short_title}.md"
    cover_md_path.write_text(cover_md, encoding="utf-8")
    print(f"Cover letter saved: {cover_md_path}")

    if args.pdf:
        chrome_path = find_chrome()
        if not chrome_path:
            print("ERROR: --pdf requested but no Chrome/Chromium install found "
                  f"(checked {CHROME_CANDIDATES})", file=sys.stderr)
            sys.exit(1)

        if args.with_resume:
            resume_pdf_path = output_dir / f"{safe_name}_Resume_{company}_{short_title}.pdf"
            render_pdf(build_resume_html(resume_data, cfg), resume_pdf_path, chrome_path)
            print(f"Resume PDF saved: {resume_pdf_path}")

        cover_pdf_path = output_dir / f"{safe_name}_CoverLetter_{company}_{short_title}.pdf"
        render_pdf(build_cover_html(cover_data, cfg), cover_pdf_path, chrome_path)
        print(f"Cover letter PDF saved: {cover_pdf_path}")


if __name__ == "__main__":
    main()
