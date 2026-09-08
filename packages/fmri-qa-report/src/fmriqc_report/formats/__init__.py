"""Output-format drivers: compose the format-agnostic content into a document.

One driver per output format. `reportlab` renders the multi-page PDF; a future
format (HTML, PNG contact sheet, ...) plugs in here and reuses `panels` and
`summary` unchanged, re-implementing only the page composition.
"""
