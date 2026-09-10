# Changelog

Notable user-facing changes to fmri-qa are recorded here. The project follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and will adopt semantic
versioning when the first stable public interface is released.

## Unreleased

### Changed

- **The artifact's `__document__` member is stored as UTF-8 bytes (`uint8`),
  not a NumPy `<U` string**, so the readers a site is likely to already have can
  open it. npy-matlab maps exactly `u1 u2 u4 u8 i1 i2 i4 i8 f4 f8 b1` and errors
  on anything else, and RcppCNPy reads numeric types only — so a `<U` document
  was the one member neither MATLAB nor R could touch, while every measured
  array in the same archive read fine. As `uint8` it is an array they already
  handle, and because `json.dumps` escapes non-ASCII to `\uXXXX` the bytes are
  ASCII whatever a file name or scanner field contains, so MATLAB's `char()`
  converts it directly. It is also 3.8× smaller (7,436 → 1,955 bytes on a
  fixture): `<U` is UCS-4 and was spending four bytes on each ASCII character.
  No schema change — the document's content and layout are identical, only the
  envelope differs — and `load_artifact` reads both forms, telling them apart by
  dtype, because the schema version lives *inside* the document and cannot be
  consulted first. Archives written by earlier builds load unchanged.

- **`fmri-qa` and `fmri-qa-report` expand their own wildcards**, so the
  command lines this project prints work in PowerShell and cmd. A POSIX shell
  expands `data/*.nii.gz` before the command starts; PowerShell does not, so
  the line `fmri-qa-import` prints for the user to paste — `analyze with:
  fmri-qa data/*.nii.gz` — arrived as a single literal argument and failed with
  `No such file or no access: 'data/*.nii.gz'`, naming a path nobody typed and
  giving no hint that the shell was the difference. Both commands now expand a
  pattern that names nothing on disk. An argument naming an existing path is
  never treated as a pattern, so a file whose name contains `*`, `?` or `[`
  still works, and on POSIX — where the shell has already expanded — every
  argument takes that path and nothing changes. A pattern matching nothing is
  still reported as a missing input rather than dropped, so a mistyped pattern
  cannot quietly analyze fewer scans than were asked for.

- **`--artifact` files into a directory that already exists**, instead of
  failing after the analysis. With one scan `PATH` was taken literally, so the
  natural `mkdir results` followed by `--artifact results` ran the whole
  analysis and then failed moving the finished file onto the directory --
  `[WinError 5] Access is denied` on Windows, `IsADirectoryError` elsewhere,
  neither naming the actual mistake, and the metrics table printed just above
  it made the run look like it had worked. An existing directory now takes
  `<scan>.qa.npz` the same way a batch does. A `PATH` that is not an existing
  directory is still the output file name, so nothing that worked changes: a
  file and a directory cannot share a name, and the old behavior in this case
  was an error, never a written artifact.

- **dcm2niix is now a dependency of `fmri-qa-core`, not the `dicom` extra.**
  The extra spared a ~3 MB compiled binary to people who only analyze NIfTI,
  and cost more than it saved: `fmri-qa-import` was the one command that could
  be installed and still not run, and the way it broke was ordinary — a `uv
  sync` without `--all-extras` removes an extra it had installed earlier, so a
  working importer became `dcm2niix: not found` with nothing in the command
  history to explain it. Installing `fmri-qa-core` now brings a converter.
  `pip install 'fmri-qa-core[dicom]'` still installs (pip warns that the extra
  is unknown and proceeds); drop the `[dicom]` when convenient. A site running
  its own dcm2niix names it with `fmri-qa-import --dcm2niix` — note that the
  bundled binary is preferred over `PATH`, so an install that previously picked
  up a vendor build from `PATH` will now use the bundled one unless it is
  named. The "not found" message no longer points at the removed extra.

- **The row/col direction and the phase-encode axis can no longer disagree.**
  `ScanMeta.pe_dir` (published as `Provenance.pe_dir`) took the sidecar's
  `InPlanePhaseEncodingDirectionDICOM` wording when it was present, while the
  *axis* came from whichever source ranked highest — so a sidecar whose DICOM
  tag contradicted its BIDS fields produced an artifact naming one axis and
  labelling it as the other, and the report showed a direction the ghost masks
  were not built on. `pe_dir` is now the word for the axis the loader resolved,
  and is `None` when it resolved none (including a through-plane `k`, where the
  run estimates an axis from the ghost instead). `Measurements.pe_label`
  follows the same rule and names the axis the run measured on, whatever
  settled it; an explicit `--pe-axis` is still the one thing that may separate
  the two, since they answer different questions. No schema change: no field is
  added, removed or retyped, and an existing artifact keeps the value its build
  measured. Unaffected unless a sidecar contradicted itself.

- **The phase-encode axis now reads dcm2niix's `PhaseEncodingAxis`**, between
  `PhaseEncodingDirection` and the raw `InPlanePhaseEncodingDirectionDICOM` tag.
  It is what dcm2niix writes when it resolved the axis but could not determine
  the polarity from vendor private data — and the axis is the entire answer this
  pipeline needs, since ghost placement is symmetric. It outranks the DICOM tag
  because it already speaks in NIfTI array letters, where (0018,1312) speaks in
  DICOM's row/col image frame and needs a mapping of ours to become an axis. On
  an axial acquisition the two agree; where they do not, an oblique or
  transposed series previously took the DICOM tag's answer or fell through to
  the header's `dim_info`.

### Added

- **`fmri-qa-import`: DICOM in, QA-ready NIfTI out.** Point it at a directory and
  it runs [dcm2niix](https://github.com/rordenlab/dcm2niix), pinning the flags a
  QA conversion cannot be left to chance on — above all `-l o`, which keeps the
  scanner's stored integers. dcm2niix's `-l y` rescales them while still writing
  an *integer* NIfTI, so `QAScan.stored_integer` sees nothing wrong and the
  saturation check reports a clipped acquisition as clean rather than as not
  determinable; `-g i` makes the pinning stick past a site's `~/.dcm2nii.ini`.
  Each series is filed as `<date>_<time>_s<NNN>_<description>`, built from the
  BIDS sidecar because dcm2niix's `-f` template cannot produce those four fields:
  `%t` is the study's time (the same for every series in a session), `%s` is not
  zero-padded (so series 11 sorts before series 2), and `%d` keeps the protocol's
  punctuation. `--names dcm2niix` keeps dcm2niix's naming and `--filename` takes
  any template; `--dcm2niix-arg` passes anything else through, warning if it
  would undo `-l o`. The converter is the optional `fmri-qa-core[dicom]` extra,
  which carries a bundled binary; a dcm2niix on `PATH` or named with
  `--dcm2niix` works instead. New `fmriqc.convert` subpackage
  (`import_dicom`, `ImportResult`, `ImportedSeries`, `ConversionError`). See the
  README's *Importing DICOM* section.

- **The saturation check now says when it cannot answer.** An ADC rail is an
  integer artifact of the receiver, so the check requires a series that still
  carries the scanner's integers. `QAScan.from_nifti` reads the NIfTI datatype,
  records it as `QAScan.stored_integer`, and warns on a float-stored file naming
  the fix; `detect_saturation` returns `None` there, and the artifact publishes
  the whole clipping block (`clipped_any`, `clipped_kept`, `n_clipped_kept`,
  `n_clipped_pre`) as `None` — *not determinable*, which is a third answer
  distinct from "no clipping found". Shown as `?` in the `clip`/`clipPre`
  columns, `null` in `fmri-qa --json`, and a `clip not determinable` note in the
  PDF. Artifact schema version 7; an artifact from schema ≤ 6 keeps its stored
  bool, which that build did measure. Previously a float-converted NIfTI of a
  genuinely saturated acquisition reported clean, silently. Every other metric
  is unaffected. See the README's *Saturation* section for the conversion
  policy this makes explicit.

- `Provenance.slice_index` / `n_slices` record which plane of the volume the
  artifact describes, and `Measurements.phantom_contrast` the mask's
  interior-over-background ratio beside the verdict reached from it. Artifact
  schema version 5; an older archive reads them back as unknown. The report's
  acquisition line shows the slice, and its BAD PHANTOM MASK note names the
  contrast so a reader can see which test the mask failed. `fmri-qa --json`
  records carry `slice_index` and `phantom_contrast`.
- Batch failures travel with the output. The `fmri-qa --json` document lists
  `requested` inputs and an `errors` inventory (`scan`, `source`, `error`) for
  every input that failed to load, analyze, or save, beside the `scans` that
  ran; JSON schema version 5. Both commands print a one-line tally of failures
  on stderr. An `fmri-qa-report` packet missing an unreadable artifact says
  so in the PDF itself: the cover counts scans against those requested and
  lists the omitted with the reason, the appendix carries a row for each,
  every scan page's footer reads INCOMPLETE PACKET, and the subject metadata
  counts them (`write_report(..., omitted=...)`).
- **The whole Nyquist-ghost family from one set of masks.** `estimate_ghost`
  builds the region-matched signal/ghost masks once per in-plane axis and
  returns a `GhostResult` carrying the masks and every ratio measured on them;
  `QAMetrics.ghost` holds it, and the artifact's ghost regions are copied from
  it rather than rebuilt. The four percentages a table shows are unchanged.
- The BIDS sidecar is optional. A NIfTI exported without one (a scanner export
  that never went through dcm2niix) now analyzes with a warning and empty
  acquisition metadata instead of being refused.
- The TR is taken from the sidecar `RepetitionTime` when it is there, and
  otherwise from the header pixdim converted by the header's declared time
  unit; a disagreement between the two warns and names both values.
- `Provenance.n_trimmed` records how many warm-up volumes the analysis dropped,
  so `outlier_worst_frame` and the curve time axis map back to acquired volume
  numbers. Artifact schema version 4; older archives read it back as unknown.
- `fmri-qa --json` records now carry `source`, `datetime`, `tr`, `n_frames`,
  `n_trimmed`, `outlier_worst_frame`, the combined `fwhm`, and `fwhm_unit`.
  JSON schema version 3.
- `fmri-qa` and `fmri-qa-hilo` print each warning the analysis raised on
  stderr as `<scan>: warning: <message>`, attributed to the scan that raised it,
  instead of Python's default line naming a source file inside the package.
- Both distributions ship the MIT license text, and CI asserts it is installed
  with each wheel.

- **The analysis artifact.** `QAArtifact` publishes one analyzed series — its
  settings, provenance, scalar measurements, stability curves, and the four
  fBIRN summary images — fully resolved, so no consumer recomputes a metric.
  `analyze(scan)` produces one; `save_artifact`/`load_artifact` move it through
  a single versioned `.npz`.
- `fmri-qa --artifact PATH` saves the artifact for each analyzed scan (a file
  for one scan, a directory of `<scan>.qa.npz` for a batch).
- `fmri-qa-report ARTIFACT... --pdf FILE`, the new reporting command.
- Structured validation for scan data, analysis parameters, and high/low pairs.
- A versioned, standards-compliant JSON output contract.
- Atomic PDF writes and pagination for packet cover and provenance sections.
- Build-artifact smoke tests in CI.
- MIT licensing and distributable package-license metadata.
- Localization diagnostics in the artifact. `Measurements` now carries
  `phantom_fraction` (the share of the frame the phantom mask covers) and
  `roi_inside_phantom`, so a stored artifact says whether the segmentation and
  the summary ROI held — the difference between "the estimator declined" and
  "the analysis was measuring background". A report calls either failure out on
  the acquisition line, `fmri-qa` in a `loc` column, and `--json` in three
  fields (`phantom_fraction`, `phantom_mask_ok`, `roi_inside_phantom`) so a
  trend database can tell a measurement from a measurement of air. Artifact
  schema version 3; JSON schema version 2.
- Artifacts written under an older schema are migrated forward on read, with a
  warning, instead of being refused: a QA archive outlives the build that wrote
  it. Fields the older schema did not carry come back as "not recorded" — `None`
  for the localization verdicts, which `fmri-qa` shows as `loc ?` and a report
  as a quiet note — never as a fabricated pass. Only an artifact from a *newer*
  build, whose layout this one cannot know, is still refused.
- `python -m fmriqc_report`, matching `python -m fmriqc`.

### Fixed

- The report's metric catalog (the physics tier's characterization and methods
  pages) describes the calculations as implemented. SFNR is the ROI average
  of voxelwise temporal-mean over detrended-SD ratios, not the ratio of the
  ROI-mean series (which is what `fluct` uses, and now says); the ghost
  denominator is the matched signal region, not the whole phantom; ACRg is
  the absolute difference; RDC is read at the full ROI.
- `save_artifact` holds an artifact to the same contract `load_artifact`
  applies, and refuses (`InvalidArtifactError`, nothing written, an existing
  archive untouched) one that would not read back. `fmri-qa` reports the
  refusal as a per-scan write error and continues the batch. The optional
  BIDS sidecar fields are now typed at the loader: a value of the wrong kind
  (an `EchoTime` written as text, a `true` flip angle) is recorded as unknown
  with a warning naming the field, instead of passing through calculation and
  saving to fail when a report opened the result.
- The phantom verdict (`phantom_mask_ok`, the table's `loc` column, the
  report's BAD PHANTOM MASK note) now applies the same test slice selection
  does: the mask must cover a plausible share of the frame *and* stand at
  least 4x above the background it was cut from. A scan holding no phantom
  segments to roughly half the frame, so the share test alone passed it, and
  a run could warn that no slice held a phantom and then save an artifact
  recording the mask as good. `PhantomGeometry` carries the measured
  `contrast`, and the warning names which test failed.
- `fmri-qa --artifact` and `fmri-qa-report --pdf` refuse an output path that
  names one of the run's inputs — the scan, its sidecar, or an artifact — and
  exit 1 before reading anything. Both writers move a finished file over the
  destination, so an output aliasing an input used to succeed and leave an
  archive where the NIfTI was, or a PDF where the archive was. Relative
  spellings, symlinks, and hard links of the same file are all caught.
- Preserve NIfTI proxy scaling for clipping detection and nulled-edge masks.
  Convert meter/micron voxel sizes to millimeters; unknown spatial units retain
  the millimeter assumption with an explicit warning.
- Validate artifact scalar types, settings, array shapes, coordinates, masks,
  and ROI bounds on load; malformed archives raise `InvalidArtifactError`.
- Preprocessed images own read-only arrays so the full input volume can be
  freed and caller mutations cannot invalidate cached summaries. Published
  artifact arrays also own read-only copies.
- Singular, non-finite, and unconverged motion fits now warn and publish NaN
  traces and peak metrics. `MotionResult.converged` identifies usable frames;
  motion plots label unresolved frames. Existing artifact layouts remain readable.
- Reject polynomial and spline detrending with no residual degrees of freedom.

- **A TR stored in milliseconds was read as seconds.** The loader took pixdim
  without its unit, so a header in msec gave a TR of 2000 s: no warm-up volumes
  were trimmed and the detrend order, which follows the run duration, exceeded
  the frame count, so the fit absorbed the noise and every stability metric was
  measured on a residual of nothing. The unit is converted now, the sidecar
  value is preferred, and `detrend_fn` refuses an order the frames cannot
  determine rather than returning zeros that look like a very stable scanner.
- **The LICENSE never reached a built package.** `license-files` pointed
  outside the package root, which the wheel dropped and the sdist recorded as
  a `../../` path.
- A directional FWHM the run could not name (no phase-encode axis resolved)
  was printed under `fwPE`/`fwRO` as the combined FWHM, a number that answers a
  different question. The table shows `?` and `--json` emits `null`.
- A phantom mask that is a single row or column crashed `analyze` after the
  whole analysis had run, from inside the convex-hull step; it now yields the
  empty outline the artifact already allowed for.
- `fmri-qa-hilo` raised a bare `ZeroDivisionError` on a zero low-flip mean.
- The ROI-fit warning suggested `center='image'` even when that was the mode in
  use; it names the other mode now.
- `save_artifact` wrote the destination in place, so an interrupted write left
  a truncated `.npz` in the archive. It writes a temporary file beside the
  destination and moves it into place. A malformed document that failed inside
  a schema migration escaped as a bare `KeyError` instead of
  `InvalidArtifactError`.
- A vendor-nulled image edge went undetected when the NIfTI carried a nonzero
  `scl_inter`, since a stored zero reads back as the intercept.
- `snr` and `sfnr` now return NaN, rather than infinity with a NumPy warning,
  when the static-noise variance or a ROI voxel's fluctuation noise is zero.
  The core test run went from 164 runtime warnings to none.

- **Phantom segmentation on an exactly-zero background.** The intensity
  quantiles seeding the watershed used strict comparisons, so an image whose air
  is exactly 0 — a background-suppressed or mask-multiplied reconstruction —
  seeded no background at all and the whole frame was labelled phantom. Every
  mask-based metric then read background silently: the ROI-fit guard passed
  vacuously, the N/2 ghost region eroded to nothing (NaN ghost percentages), and
  SFNR divided by a noiseless floor. The seeds are now inclusive, and
  `detect_phantom` warns when a mask comes out degenerate either way.
- **`--center phantom` selecting a slice with no phantom in it.** The mode took
  the slice with the largest *segmented* area, but segmenting a slice of pure
  air still labels about half the frame — more than a real cross-section — so a
  prescription running past the end of the phantom analyzed background instead.
  A slice now counts only if what its mask selected stands clear of the
  background it was separated from; if no slice does, the middle slice is used
  and a warning says so.
- **SNR biased low on an odd number of analyzed frames.** The static-noise
  difference image sums the odd frames against the even ones; with an odd frame
  count the two subsets differ by one, so the difference carried a whole frame of
  *signal* and its spatial variation across the ROI — not noise — set the
  denominator. A phantom shaded 25% across the FOV read 25% low, and because
  parity follows `--trim-sec`, the same series scored differently for a
  one-volume change in the warm-up trim. The difference is now formed over
  balanced subsets; the signal still averages the full series.
- **A phase-encode axis reported when none was measured.** The estimate picks
  the axis whose Nyquist ghost region is brighter, but an axis the ratio could
  not be measured on scores NaN — and every comparison against NaN is False, so
  `max` returned whichever axis it looked at first. An image with no measurable
  ghost (a collapsed segmentation, a phantom spanning the FOV) therefore always
  reported "axis 0", with four ghost percentages sampled from wherever that
  pointed, and an axis measurable on only one side could be resolved to the
  other. Only measurable axes are candidates now, and when neither is,
  `estimate_pe_axis` returns `None`: the run continues with the ghost metrics
  undefined and a warning, the artifact records no axis, and a report labels the
  direction "?" and draws no ghost regions.
- **`fmri-qa --artifact` silently discarding a scan.** A batch names each
  artifact after the scan's stem, so inputs sharing a file name across
  directories (`a/scan.nii.gz`, `b/scan.nii.gz`) overwrote one another and a
  later report packet was quietly missing scans. Such a batch is now refused
  before any analysis runs.
- `fmri-qa-report --pdf` creates the destination directory instead of failing on
  the name of the atomic write's temporary file.

### Changed

- Every frozen value object in `fmriqc` now declares `slots=True`, as the
  artifact-side ones already did — an attribute a typo invents is rejected
  rather than silently created. `QAImages` is the one exception and now says so
  at its decorator: its summary images are `cached_property`, which needs a real
  instance `__dict__` to cache into.
- `analysis.build._provenance` no longer re-lists the nine identifying
  `Provenance` fields to add the sidecar block to them; `dataclasses.replace`
  carries them. Every sidecar field is still spelled out, since the artifact's
  acquisition block is a published contract.

- **The detrender is a value object, not an anonymous `(callable, int)` pair.**
  `prep.detrend.Detrender` carries the `method` and the `order` it resolved to
  and *is* the operator: `Detrender.for_series(center_slice, tr, method)`
  derives the fit complexity, and calling the result detrends an array.
  It replaces `detrend_fn`, whose returned tuple callers destructured
  positionally -- `hilo.stats` discarded the order with a `_`, and `preprocess`
  recorded `QAImages.detrend_method` from its own *argument* while taking the
  order from the fit, two sources for one decision. Both now read off the
  detrender that actually ran. Applying a detrender dispatches on `method` as
  exhaustively as choosing one does, so a new `DetrendMethod` member is a type
  error at both ends. Detrended output is unchanged, bit for bit.
  `Detrender` is exported from `fmriqc` in place of `detrend_fn`.

- **Adding an option to a closed set is now a type error at every place that
  dispatches on it.** The three functions that switch on an option `Literal`
  -- `detrend_fn` (`DetrendMethod`), `resolve_roi` and `select_slice`
  (`RoiCenter`) -- ended in a fall-through `raise InvalidChoiceError`, so a new
  method or localization mode type-checked clean everywhere and failed only at
  runtime, on the scan that first used it. Each now guards the runtime contract
  up front and then matches exhaustively, ending in `typing.assert_never`:
  the guard keeps the same `InvalidChoiceError` and message for an untyped
  caller, while the match makes an unhandled member fail `mypy` and `pyright`.
  `detrend_fn`'s two branches move into `_poly_detrender`/`_spline_detrender`
  and `select_slice`'s phantom search into `_largest_phantom_slice`, so the
  dispatch reads as dispatch. No behaviour changed, warning attribution
  included.

- **A detected clip rail is one object, so its fields cannot come apart.**
  `SaturationResult` carried `ceiling`, `bits`, `worst_volume` and
  `worst_count` as four independently-optional fields that `detect_saturation`
  always set together or not at all; they now sit behind a single
  `rail: ClipRail | None`. `ceiling` and `bits` remain readable as properties,
  so the artifact's flat `clip_ceiling`/`clip_bits` fields are unchanged, as are
  `suspected`, `clipped`, `clipped_kept` and the two trim-split counts --
  those stay on the result because zero is a true answer for them, where
  "which volume was worst" has none without a rail. `ClipRail` is exported
  from `fmriqc`.

- **The in-plane voxel size is a value object that carries its own unit.**
  `prep.scale.VoxelSize` holds the in-plane mm/voxel pair (or None when the
  header did not say) and answers the three questions the length-reporting
  metrics each used to answer for themselves: `unit` ("mm" when the size is
  known, else "vox"), `per_axis` (the scale factor, 1.0 when it is not), and
  `magnitude` (per-axis displacements to a length). `MotionResult`,
  `CenterOfMassResult` and `SmoothnessResult` now carry a `voxel: VoxelSize`
  in place of `voxel_mm: tuple[float, float] | None`, and their estimator
  functions still take a plain `voxel_mm=` tuple, so call sites are unchanged.
  This removes two byte-identical `displacement` implementations, a third
  per-axis scaling helper, and the three separate spellings of
  `"mm" if voxel_mm is not None else "vox"` in the artifact builder;
  `prep.imaging.normalize_voxel_mm` is superseded by the constructor, which
  coerces the header's numpy scalars to plain floats. No metric value, unit, or
  artifact field changed. `Provenance.voxel_mm` and `ScanMeta.voxel_mm` are a
  different thing (the full three-axis header zooms) and are untouched.

- **The phase-encode axis is a closed type, not a bare `int`.** `PeAxis`
  (`Literal[0, 1]`) and its derived `PE_AXES` tuple join the option `Literal`s
  already in `fmriqc.types`, and everything from `preprocess` inward is
  annotated with it: the ghost family, the smoothness result, the pipeline's
  resolution, and the artifact's `settings.pe_axis_override` /
  `measurements.pe_axis`. The loader still reads a plain `int | None`, because
  a BIDS sidecar may legitimately name the through-plane axis; the single
  narrowing point between the two is the new `load.pe_axis.in_plane`. Three
  runtime domain checks fall out as a result — `SUPPORTED_PE_AXES` (now
  `PE_AXES`) and the two `pe_axis in (None, 0, 1)` assertions in the artifact
  validator, which the field annotations now carry on both save and load.
  `PE_ROWCOL` is keyed by `PeAxis` and so is total, retiring the two-step
  lookup the artifact builder used to reach a `PeLabel` through. The readout
  axis has one definition, `types.readout_axis`, in place of three inline
  `1 - pe_axis` spellings. `fmri-qa --pe-axis` takes the same `{0,1}` it always
  did, and no metric value changed.
- `QAMetrics.pe_axis` is now a property reading `ghost.pe_axis` rather than a
  field beside it. The axis and the ghost family are one fact — there is no
  ghost result without an axis, and `estimate_ghost` already records the axis
  it measured on — so a second copy could only agree or be a bug, and
  "resolved an axis but measured no ghost" was a state the type allowed. Reading
  `metrics.pe_axis` is unchanged; constructing a `QAMetrics` no longer takes
  (or accepts) a `pe_axis=` argument.

- **Three files that had grown into several topics are now subpackages**, by
  the one-file-one-topic rule in `style/architecture.md`. `fmriqc.cli` splits
  into a module per command (`qa`, `hilo`) plus the pieces they report through
  (`table`, `record`, `destinations`, `arguments`);
  `fmriqc.analysis.serialize` splits at its own section banners into
  `decompose` / `compose` / `migrate`; and `fmriqc_report.formats.reportlab`
  into `layout` / `pages` / `packet` / `svglib_patch`. Every import path a
  caller uses is unchanged — `fmriqc.cli:main`, `fmriqc.cli:hilo_main`,
  `fmriqc.save_artifact`/`load_artifact`, `fmriqc_report.write_report` — and
  no rendered output changed.
- `fmriqc.hilo` (307 lines) is now a subpackage by the same rule: `result`
  holds `HiLoResult` and the pure `separate_noise` algebra that fills it,
  `mask` holds `phantom_core_mask` and its `HILO_ERODE` tuning constant,
  `stats` holds the per-scan mean/SD reduction, and `compatibility` holds the
  geometry/acquisition checks; `__init__` keeps the `run_hilo` orchestration.
  `fmriqc.hilo`, `run_hilo`, `HiLoResult`, `separate_noise`, `phantom_core_mask`,
  and `HILO_ERODE` all still import from `fmriqc` exactly as before, and
  `fmriqc.__all__` is unchanged. The two helpers `run_hilo` calls across the
  new module boundary are now public (`hilo_stats`, `require_compatible_scans`)
  rather than underscore-prefixed, for the same reason as below.
- The report's format-agnostic content API is spelled public, since the
  format drivers in `formats/` are documented to consume it: `panels.timeseries`
  exports `plot_*`, `panels.images` exports `panel_figs`, and `summary` exports
  `acquisition_line` / `device_line` / `provenance_line` / `appendix_rows`.
  `fmriqc_report.__all__` is unchanged, so the distribution's public surface
  is the same. Likewise `prep.imaging.clamp_center` / `geomean`, which the
  geometry and smoothness modules already imported across module lines.
- `run_qa` writes the settings it was called with onto `QAResult.settings`
  (with the detrend order it resolved), and `build_artifact(result)` publishes
  those; its `settings` parameter is gone. It used to fill in defaults when
  none were passed, so a result computed with no trim, phantom centering, or
  a forced PE axis could be published as the default run. `AnalysisSettings`
  lives in `fmriqc.pipeline` (still exported from `fmriqc`), and its
  `roi_size` is now the side *requested*; the side analyzed is
  `images.roi.size`, as it always was.
- The phase-encode axis is estimated from the Nyquist ghost in one place, the
  pipeline. `QAScan.from_nifti` no longer estimates it (its `estimate_pe`
  parameter is gone) and only reports what the sidecar and header say, so the
  load layer no longer depends on the metrics layer.
- `Measurements.fwhm_unit`, `Measurements.pe_label`, and `PsfCurves.unit` are
  closed sets (`LengthUnit`, `PeLabel` in `fmriqc.types`), and `load_artifact`
  refuses a stored value outside them. `FBIRN_ROI_SIZE` lives in
  `fmriqc.types`, shared by the ROI resolver and the artifact's default.
- `QAImages` caches its derived summary images instead of recomputing each
  full-slice reduction on every access.
- The `notebooks` extra is no longer published with `fmri-qa-core`; the
  notebook stack is a root dependency group taken with `make sync-notebooks`.
- pre-commit runs the locked `ruff` through `uv run`, so the hook and
  `make check` cannot disagree on formatting. The style guides describe the
  tooling this repository actually has.

- **The project is now two distributions.** `fmri-qa-core` (import `fmriqc`)
  holds the calculation half and depends on nothing that draws; `fmri-qa-report`
  (import `fmriqc_report`) holds the plots and PDF packets and consumes only a
  `QAArtifact`. Installing `fmri-qa-report` brings both. The single `fmri-qa`
  distribution is gone; see `notes/analysis_report_split.md`.
- A report header now shows the phase-encode direction that was actually used.
  It previously preferred the sidecar's DICOM direction even when `--pe-axis`
  overrode the axis, so the header could disagree with the metrics table.
- Phase encoding is explicitly limited to the in-plane axes supported by the
  single-slice metrics.
- The svglib image-alignment workaround now probes compatibility before use, and
  is installed on the first render rather than at import: it mutates a
  third-party class process-wide, and an unrecognized svglib should fail the
  render that needs it rather than `import fmriqc_report`.
- `fmri-qa-report` declares its dependency on `cycler`, which its `Theme` imports
  directly and which had until now arrived only as a matplotlib transitive.

### Removed

- `MissingSidecarError`: a missing sidecar is a warning now, not an error.
- `ghost_top_ratio`, `acr_ghosting_ratio`, and `phase_encode_axis`; their
  measurements come from `GhostResult`, and `QAMetrics` carries that result
  instead of four loose percentages.

- `fmri-qa --pdf`, `--pdf-tier`, `--pdf-cover`, and `--pdf-appendix`. Rendering
  moved to `fmri-qa-report`, whose equivalents are `--pdf`, `--tier`, `--cover`,
  and `--appendix`; producing a report is now two commands.
