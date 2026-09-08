// ─── CareerOS canonical resume template: "modern" ──────────────────────────
// Compiles standalone:  typst compile app/templates/typst/modern.typ resume.pdf
// The Python renderer (app/services/pdf/typst_compiler.py::render_document_model_to_typst)
// mirrors this styling for live resumes; keep the two in sync.
//
// ATS-friendly by construction: single-column flow, real selectable text,
// standard section headings, tight fixed margins (1.2cm) so content cannot
// silently overflow to extra pages. All candidate data arrives through the
// `#let data` dictionary below (structured JSON shape); user strings are
// inserted via `#t(...)` so leading `=`/`-`/`@`/`#` characters in resume
// text can never be parsed as Typst syntax.

// ─── Structured resume data (JSON shape) ─────────────────────────────────
#let data = (
  name: "Asha Engineer",
  headline: "Backend Engineer · Python / FastAPI",
  contact: "asha.engineer@example.com | +91 98765 43210 | Bengaluru, IN | linkedin.com/in/ashaengineer",
  summary: "Backend engineer building payment APIs with Python and FastAPI. Cut P99 latency by 35% owning the Redis caching layer.",
  experience: (
    (
      role: "Backend Engineer",
      company: "Finscale",
      dates: "2022 — Present",
      location: "Bengaluru, IN",
      bullets: (
        "Built ingestion microservices with Python/FastAPI handling payment webhooks.",
        "Optimized PostgreSQL queries, reducing P99 latency by 35%.",
      ),
    ),
  ),
  skills: (
    ("Technical", "Python, FastAPI, PostgreSQL, Redis"),
    ("Tools", "Docker, GitHub Actions"),
  ),
  education: (
    (
      degree: "B.Tech in Computer Science",
      institution: "Visvesvaraya Technological University",
      dates: "2018 — 2022",
      meta: "CGPA: 8.7",
    ),
  ),
  projects: (),
)

// ─── Page + typography ───────────────────────────────────────────────────
#set page(paper: "a4", margin: (x: 1.2cm, y: 1.2cm))
#set text(font: ("DejaVu Sans",), size: 9.5pt, fill: rgb("#1e293b"))
// NOTE: par(spacing:) needs Typst 0.12+; the pinned 0.11.1 uses block spacing.
#set block(spacing: 4pt)
#set par(leading: 0.45em)

// Literal-text helper: content from variables is never parsed as markup.
#let t(it) = [#it]

#let rsec(title) = {
  v(6pt)
  text(size: 10.5pt, weight: "bold", fill: rgb("#0f172a"), tracking: 0.06em, upper(title))
  v(2pt)
  line(length: 100%, stroke: 1pt + rgb("#cbd5e1"))
  v(3pt)
}

// ─── Header ──────────────────────────────────────────────────────────────
#align(center)[
  #text(size: 20pt, weight: "bold", fill: rgb("#0f172a"))[#t(data.name)]
  #v(2pt)
  #text(size: 11pt, weight: "bold", fill: rgb("#475569"))[#t(data.headline)]
  #v(2pt)
  #text(size: 8.5pt, fill: rgb("#64748b"))[#t(data.contact)]
]

// ─── Summary ─────────────────────────────────────────────────────────────
#rsec("Professional Summary")
#t(data.summary)

// ─── Experience ──────────────────────────────────────────────────────────
#rsec("Experience")
#for exp in data.experience [
  #grid(
    columns: (1fr, auto),
    gutter: 8pt,
    [#text(size: 10pt, weight: "bold", fill: rgb("#0f172a"))[#t(exp.role + " | " + exp.company)]],
    [#text(size: 8.5pt, fill: rgb("#64748b"))[#t(exp.dates + " | " + exp.location)]],
  )
  #list(marker: [•], spacing: 2pt, indent: 12pt, body-indent: 6pt, ..exp.bullets.map(b => [#t(b)]))
  #v(3pt)
]

// ─── Skills ──────────────────────────────────────────────────────────────
#rsec("Skills")
#for (cat, vals) in data.skills [
  #text(size: 9.5pt)[#strong[#t(cat + ":")] #t(vals)]
]

// ─── Education ───────────────────────────────────────────────────────────
#rsec("Education")
#for edu in data.education [
  #grid(
    columns: (1fr, auto),
    gutter: 8pt,
    [#text(size: 10pt, weight: "bold", fill: rgb("#0f172a"))[#t(edu.degree + " — " + edu.institution)]],
    [#text(size: 8.5pt, fill: rgb("#64748b"))[#t(edu.dates)]],
  )
  #text(size: 8.5pt, fill: rgb("#64748b"))[#t(edu.meta)]
  #v(3pt)
]

// ─── Projects (omit when empty) ──────────────────────────────────────────
#if data.projects.len() > 0 [
  #rsec("Projects")
]
