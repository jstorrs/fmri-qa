"""Output-format drivers: compose the format-agnostic content into a document.

One module per output format. `reportlab` renders the multi-page PDF; a future
format (HTML, PNG contact sheet, ...) plugs in here and reuses `report.panels`
and `report.summary` unchanged, re-implementing only the page composition.
"""
