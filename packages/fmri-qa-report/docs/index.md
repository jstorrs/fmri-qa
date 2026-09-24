# fmri-qa-report: rendering the result

The presentation half of fmri-qa. It renders one
{external+core:doc}`analysis artifact <artifact>` into a single self-contained
HTML page that opens by double-click, with no network and no companion file.

The artifact is its only input. Every number, curve, mask and image a report
draws was computed by `fmri-qa-core` and stored in the file, so a report can be
rendered on another machine, long after the scan, with none of the acquisition
data at hand — and an artifact read back from disk renders exactly like one
just computed. Nothing here recomputes a metric.

Inside, content is kept separate from format: `summary` and `content` build the
text, `panels` draws the matplotlib figures, and `formats/` holds one driver
per output format. HTML is the one format today; another would be a new driver
reusing the same content and panels.

```{toctree}
:maxdepth: 2

usage
page
library
```

## Where to start

- **"How do I turn a `.qa.nc` into a page?"** — {doc}`usage`.
- **"Can I put this on our website, or attach it to a QA record?"** —
  {doc}`page` says what the file contains, what it needs from the browser, and
  what an embedding site's Content-Security-Policy has to allow.
- **"Can I render one from my own code, in our colors?"** — {doc}`library`.
