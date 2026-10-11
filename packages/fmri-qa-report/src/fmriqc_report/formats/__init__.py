"""Output-format drivers: compose the format-agnostic content into a document.

One driver per output format. `html` renders the self-contained run page. A
future format (PNG contact sheet, ...) plugs in here and reuses `panels` and
`summary`, rewriting only the page composition.
"""
