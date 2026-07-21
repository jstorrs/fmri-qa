# Report redesign: tiers, themes, and packets

Status: implemented (all five phases; see [Phasing](#phasing)). Remaining
follow-up: the deferred acceptance-threshold subsystem.

This document describes the target structure for the `fmriqc.report` subpackage.
It supersedes the ad-hoc `--pdf-layout summary|detailed` split with a design
built around the three things reports are actually asked to do.

## Motivation

Reports serve two audiences and one packaging need:

1. **A high-level dashboard** for technologists and researchers — the top-line
   numbers and at-a-glance images, in plain language, one page per scan.
2. **A detailed physics-QA document** for commissioning and performance
   characterization — the dashboard content plus per-metric definitions,
   acceptance context, the methods/provenance narrative, and full acquisition
   parameters.
3. **A styled packet** that combines several scans/tests into one branded
   document, where a physicist or group carries a consistent identity (fonts,
   colours, logo, cover, running header/footer) across everything they issue.

The current driver conflates these. `--pdf-layout summary|detailed` mixes *depth*
(how much content) with page count, every visual decision is a literal buried in
`formats/reportlab.py` (Helvetica, gray `0.96` tiles, `letter`, a 40 pt margin),
and the matplotlib panels carry a *second*, independent set of style constants —
so there is no single place to rebrand, and the page furniture and the embedded
figures cannot be kept visually consistent.

## The three axes

The redesign decouples what the current code fused into one `layout` argument.
A report is a point in a three-axis space, and the axes are independent:

| Axis | Question | Values |
|------|----------|--------|
| **Depth tier** | *what content, at what altitude* | `dashboard`, `physics` |
| **Theme** | *how it looks* | any `Theme` instance |
| **Composition** | *what is assembled* | cover? sections; appendix? |

`depth × theme × composition` yields every deliverable from two tiers and N
themes, instead of one hard-coded page function per combination.

### Depth tier

- **`dashboard`** — status, the KPI metric tiles, the phantom-image row, and the
  core stability curves. Plain-language labels. One page per scan.
- **`physics`** — the dashboard `overview` page *verbatim*, then a full-size
  `stability` page, a per-metric **characterization** table (definition, measured
  value, and — once thresholds land — the acceptance window and its provenance),
  and a **methods** page of the algorithm/provenance prose. Parts:
  `("overview", "stability", "characterization", "methods")`.

**`dashboard` is a strict prefix of `physics`.** This settles the open question
recorded in the `project_pdf_report_tiers` memory: `physics` is `dashboard`'s
block list plus `characterization` and `methods`, so the two tiers cannot drift
and a technologist and a physicist read the same top-line page.

### Theme

A `Theme` is the single source of every visual decision, consumed by **both**
renderers — the ReportLab page furniture and the matplotlib panels. Threading one
object through both is what keeps an embedded figure visually consistent with the
page around it; today they are styled independently and cannot be kept in step.

Decision: a **Python `Theme` object** (a frozen dataclass), not an external
theme file. It is type-checked, testable, needs no new file format or parser, and
a group brands by instantiating or subclassing it. The trade-off — branding is a
code change, not a data file — is acceptable for the current, developer-adjacent
user base; a declarative loader can be layered on later without disturbing the
object model, because the object is the interface the renderers see either way.

### Composition

A report is a list of **blocks** the driver walks, rather than a fixed sequence of
page functions:

```
Cover?  →  [ ScanSection per scan ]  →  Appendix?
```

The "styled packet" need is then just a composition with a `Cover`, several
`ScanSection`s, and a shared `Appendix`, all wearing one `Theme`. This generalises
today's `write_report`, which concatenates scans with no cover, no shared
identity, and no appendix.

## Module layout

```
report/
    theme.py          NEW  — the Theme dataclass + its adapters (rc_params, tile/text styles)
    document.py       NEW  — the block model (Cover, ScanSection, Appendix) + compose()
    content.py        NEW  — per-metric metadata: label, units, definition, methods prose
    summary.py        keep — format-agnostic content (tiles + metadata lines)
    panels/           keep — figures, now taking a Theme so colours/fonts match the page
    formats/
        reportlab.py  refactor — consumes a Theme, walks a block list; no literal styling
```

Two new modules (`theme`, `document`), one new data module (`content`); the
existing content modules lose their hard-coded styling to `Theme`. This stays
inside the `report/` layer and honours the content-vs-format split already
documented in `style/architecture.md`.

## The `Theme` object

A frozen dataclass; the default instance reproduces the current appearance
exactly, so introducing it changes no pixels.

```python
@dataclass(frozen=True, slots=True)
class Theme:
    # page
    page_size: tuple[float, float] = letter
    margin: float = 40.0
    # typography (family names resolved to registered fonts)
    font_title: str = "Helvetica-Bold"
    font_body: str = "Helvetica"
    font_numeric: str = "Helvetica-Bold"   # the big tile values
    # colour
    text_gray: float = 0.40
    tile_fill: float = 0.96
    tile_stroke: float = 0.80
    pass_warn_fail: tuple[str, str, str] = ("#2e7d32", "#f9a825", "#c62828")  # reserved
    # panels
    panel_cmap: str = "gray"
    panel_accent: str = "#1f77b4"          # matplotlib "tab:blue"
    # brand furniture
    logo: Path | None = None
    footer: str = ""
    cover_title: str = "fMRI QA Report"

    def rc_params(self) -> dict[str, object]: ...   # matplotlib rcParams for the panels
```

The panels wrap figure construction in `matplotlib.rc_context(theme.rc_params())`
and read `panel_cmap` / `panel_accent` for the marks they draw, so the fonts and
accent of an embedded SVG match the ReportLab-drawn furniture around it.

`pass_warn_fail` is present but unused until thresholds land (see below); reserving
the field now keeps the traffic-light slot obvious.

## Deferred: acceptance thresholds

Pass/warn/fail limits are **out of scope for this redesign** and land as a
follow-up. Until then:

- `dashboard` tiles render measured **values only**, with no traffic-light colour.
- The `physics` characterization table shows definition, units, and value, with an
  empty acceptance column.

The structure leaves a clean slot: a future `ThresholdSet` feeds the tile and
characterization renderers, and `Theme.pass_warn_fail` already carries the palette.
The FBIRN correctness bar (`feedback_fbirn_correctness_bar`) sets the eventual
default limits.

## CLI surface

`--pdf-layout summary|detailed` is renamed to `--pdf-tier dashboard|physics`, a
clean break made at the redesign — the moment the `project_pdf_report_tiers` memo
reserved for settling the naming. CLI flags are a data interface
(`style/stability.md`), so this is a deliberate, documented break, acceptable
pre-release with no external consumers. The "N pages" notice already counts pages
actually drawn and is unaffected.

## Phasing

Each phase is a self-contained, reviewable commit that keeps the gate green. The
early phases are pure refactors: with the default `Theme`, output is unchanged.

1. **[done] `Theme` for the driver.** Add `theme.py`; thread a `Theme` through
   `formats/reportlab.py` (page size, margin, fonts, tile/header colours),
   replacing the literals. Panels untouched. Default theme ⇒ identical output.
2. **[done] `Theme` for the panels.** Add `rc_params()` and the panel colour
   fields; build the panels under `matplotlib.rc_context` in the driver so the
   figures follow the theme. Now one object styles the whole report.
3. **[done] Block model + `compose` + CLI.** Add `document.py`; the driver walks
   a `ScanSection`'s `parts`, one renderer per part; `physics` = `dashboard`
   parts + `stability`. `--pdf-layout summary|detailed` renamed to
   `--pdf-tier dashboard|physics`. The image-grid page (`_summary_page`) is
   retired — the overview already carries the compact image row; a large-image
   part can return in phase 5 alongside characterization.
4. **[done] Cover + Appendix + furniture.** Add the `Cover` and `Appendix`
   blocks and their renderers, a running footer (brand text + page numbers, shown
   once a packet spans pages), and `--pdf-cover`/`--pdf-appendix` flags. Rebranding
   is proven by tests (a themed logo/footer/cover packet) rather than a shipped
   named theme, which would be arbitrary library content. Delivers the packet
   capability. Note: the appendix assumes it fits one page (no mid-page break yet).
5. **[done] `content.py` + characterization/methods.** Add `content.py`: a
   `MetricDoc` catalog (`METRIC_DOCS`) that single-sources each metric's label,
   value formatter, definition, and method prose. The header tiles now read it
   (`metric_tiles`, moved out of `summary.py`), and the `physics` tier gains a
   `characterization` page (value + definition, acceptance column stubbed "--"
   pending thresholds) and a `methods` page. Tiles and the characterization table
   are proven to share labels and values by test.

Phases 1–3 are foundational and change no user-visible output under the default
theme; 4–5 deliver the new dashboard/physics/packet capabilities.
