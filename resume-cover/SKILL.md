---
description: Tailor a resume and cover letter for a job posting
arguments:
  - name: url
    description: URL of the job posting
    required: true
---

# Resume & Cover Letter Generator

Create a tailored cover letter for a specific job posting. **Do NOT generate a
tailored resume unless explicitly asked** -- default to the user's own master
resume as-is for actual submissions; a per-role tailored resume is a non-default
extra, not part of the normal flow.

## Setup

Before first use, create a `config.json` in this skill's directory:

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

## Inputs

- **Job posting URL:** $ARGUMENTS.url
- **Source resume:** path from `config.json` — read directly if it's `.md`/`.txt`;
  if it's `.docx` or `.pdf`, extract text first (Read handles PDF directly; for
  docx use `python3 -c "import zipfile, xml.etree.ElementTree as ET; ..."` or
  python-docx if installed).
- **Generator script:** `generate_resume_cover.py` in this skill's directory —
  writes Markdown, and PDF too if asked.

## Steps

1. **Read config.json** from this skill's directory. All personal info comes from there.

2. **Fetch the job posting** from the provided URL using WebFetch. If the content
   doesn't load fully (dynamic pages), try WebSearch to find the posting on LinkedIn
   or other mirrors. Extract: job title, company, location, compensation,
   responsibilities, required qualifications, preferred qualifications.

3. **Read the source resume.** This is the user's master resume — use it as the
   factual basis. Never invent experience or skills that aren't in the source resume.

4. **Analyze the match.** Identify:
   - Strongest alignments with the role
   - Any gaps to address honestly (e.g., framework preferences)
   - Key language/phrases from the posting to mirror

5. **Tailor a resume -- only if explicitly asked.** Skip this step by default; the
   generator won't produce one unless `--with-resume` is passed (step 7). If asked:
   - Rewrite the Professional Summary to lead with what matters most for THIS role
   - Reorder and reframe bullet points to emphasize relevant experience
   - Add relevant skills keywords from the posting to Technical Skills (only if
     genuinely possessed)
   - Trim older/less-relevant roles to keep it concise
   - Mirror the posting's language where authentic
   - Do NOT fabricate experience, inflate titles, or add skills not in the source
   - Watch the years-of-experience framing specifically: check `profile.years_experience_note`
     in `../config.json` before writing any "N years of X experience" claim. Total
     career years and frontend-specific years are NOT the same number here.

6. **Write the cover letter.** Structure:
   - Opening: specific interest in the role and company, 1-sentence positioning
   - 2-3 body paragraphs with bold lead-in phrases, each mapping a key requirement
     to concrete experience
   - If there's a notable gap, address it head-on with a confident reframe
   - Closing: why this company/role specifically, invitation to discuss
   - Tone: confident, specific, not sycophantic. Show don't tell.

7. **Generate the files.** Write `cover_letter_tailored.json` (structured cover
   letter data) to the output directory -- and `resume_tailored.json` too, but
   only if step 5 applies. See the script source for the exact JSON schemas.
   Then run the generator:
   ```
   python3 "<this skill dir>/generate_resume_cover.py" --config "<this skill dir>/config.json" --pdf
   ```
   Cover letter Markdown is always written; add `--with-resume` if (and only if)
   a tailored resume was explicitly requested. `--pdf` additionally renders
   submission-ready PDF(s) via headless Chrome (drop the flag if the user just
   wants to review the Markdown first).

8. **Report** the output file paths and a brief summary of tailoring choices made.
   Before touching a file that already exists from a prior run, check the
   applications tracker status for that company/role first -- see
   [[job-search-check-before-editing-materials]] equivalent: don't assume
   "materials ready" means still safe to overwrite; ask if there's any doubt
   about whether it's already been submitted.

## Output files

All output goes to the configured `output_dir`:
- `{Name}_CoverLetter_{CompanyName}_{ShortTitle}.md` (always)
- `{Name}_Resume_{CompanyName}_{ShortTitle}.md` (only with `--with-resume`)
- with `--pdf`: matching `.pdf` file(s), ready to submit

## Important rules

- Markdown is the source of truth; PDF is a rendered submission artifact, not something to hand-edit
- Use the source resume as the single source of truth for experience
- Never invent, exaggerate, or fabricate any experience or skills
- Keep the resume to 2 pages max
- Address gaps honestly rather than hiding them
