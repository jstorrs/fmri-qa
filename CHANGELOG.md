# Changelog

Notable user-facing changes to fmri-qa are recorded here. The project follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and will adopt semantic
versioning when the first stable public interface is released.

## Unreleased

### Changed

- **Loaded scan affines now use millimeters, matching their voxel sizes.**
  Equivalent NIfTI geometry encoded in meters, millimeters, or microns can now
  be paired for high/low analysis. Conversion includes affine translation;
  unknown spatial units assume millimeters with one warning per scan. Direct
  `QAScan` callers must supply affines in millimeters too.
- **Outlier plots no longer show `qthr` as a chance fraction.** The threshold
  uses `Q^-1(qthr / n_frames)`, so `qthr` is a tuning parameter, not an expected
  per-frame outlier fraction. Report and analysis documentation now describe
  that distinction, and the misleading reference line is removed. The
  estimator, default, numeric results, and stored `outlier_qthr` field are
  unchanged.
- **An `AnalysisSettings` with an impossible knob is now an `InvalidScanError`
  at construction.** The record that is the run's request held none of its own
  domains: a non-finite or negative `trim_sec`, a `roi_size` of zero or less,
  and a negative `detrend_order` were checked by `validate_qa_run` for a run and
  again, in a second spelling, by `validate_artifact` at the archive door, so a
  record built for either and used for neither carried a knob nothing could
  honour. `AnalysisSettings.__post_init__` holds all three now, as the three
  artifact records above hold theirs, and both validators keep only what they
  alone can see — for `validate_qa_run`, what the request means for *this* scan.
  `InvalidScanError` rather than the `ValueError` those records raise, because
  it is the error the pipeline already refused these values with and it carries
  the field and value; it is a `ValueError` too, so a stored document that
  breaks a domain still fails its load as an `InvalidArtifactError`. The
  on-disk layout, `ARTIFACT_SCHEMA_VERSION` and the CLI are untouched.
- **`run_qa` and `preprocess` take an `AnalysisSettings` record instead of loose
  knobs.** The five request knobs and every one of their defaults were spelled
  in `AnalysisSettings`, again in `run_qa`'s signature, and three of them a
  third time in `preprocess`'s, with `analyze` unpacking the record it held back
  into keyword arguments; a default edited in one spelling alone left
  `analyze(scan)` and `run_qa(scan)` disagreeing about what an unqualified run
  is. `AnalysisSettings` is now the library's single definition of every
  analysis default, and the record a run answered is the record it publishes. A breaking change to
  a pre-release API: `q.run_qa(scan, roi_size=9)` becomes
  `q.run_qa(scan, q.AnalysisSettings(roi_size=9))`, and `pe_axis` is the
  record's `pe_axis_override`. The CLI, its flags and the on-disk artifact are
  unchanged.
- **`phantom_plausible` now takes `fraction` and `contrast` as keyword-only
  arguments.** The two are same-typed floats on different scales — a share of
  the frame in [0, 1] and a phantom/background intensity ratio typically well
  above 1 — with an order nothing at a call site revealed, so a swap
  type-checked and silently inverted the single definition of "this
  segmentation held": the figure slice selection ranks slices by and the
  artifact publishes as `phantom_mask_ok`. All three call sites now name both
  arguments.
- **An impossible `Provenance` or `RoiBox` is now a `ValueError` at
  construction too.** The same, for the two records that describe the run and
  the ROI box: a series with no frames, a non-positive or non-finite `tr`, a
  `slice_index` past the `n_slices` beside it, a voxel with no size, and a ROI
  box that is not square or whose bounds run backwards are refused by
  `Provenance.__post_init__` and `RoiBox.__post_init__`. `validate_artifact`
  keeps only what it alone can see — that the box also lies inside the image it
  is drawn on. Messages, the on-disk layout, and `ARTIFACT_SCHEMA_VERSION` are
  unchanged.
- **A `Measurements` that contradicts itself is now a `ValueError` at
  construction, not an `InvalidArtifactError` at save.** The record's
  single-record invariants — a directional `fwhm_pe`/`fwhm_ro` beside a
  `pe_axis` that resolved, a clipping block answered as a unit, each flag
  agreeing with its count, a `phantom_contrast` that is non-negative or
  unrecorded — were checked
  only by `validate_artifact`, which runs at the archive door; an artifact
  built in-process and printed or rendered without ever being saved was never
  checked at all. `Measurements.__post_init__` holds them now, so the illegal
  record cannot be built. What is refused is unchanged, down to the message
  text: a stored document that breaks one still fails its load as an
  `InvalidArtifactError`, and the on-disk layout and
  `ARTIFACT_SCHEMA_VERSION` are untouched.
- **`QAImages.detrend_method` and `.detrend_order` are one field, `detrender:
  Detrender | None`.** The pair was one fact split in two — the order means a
  polynomial degree or an interior-knot count depending on the method, so a
  `QAImages` could claim a fit that never ran (spline, degree 3 from a poly
  fit). `preprocess` now sets `detrender` to the exact `Detrender` it applied;
  `AnalysisSettings.detrend_order`, the published artifact value, is
  unchanged.
- **`estimate_motion`, `estimate_center_of_mass` and `estimate_smoothness` take
  a `VoxelSize` instead of a raw `voxel_mm` tuple.** Each rebuilt its own
  `VoxelSize(voxel_mm)` from the same header pair `run_qa` had already sliced,
  the type whose whole purpose is to be the one answer to "is the size known,
  what is it on this axis" -- three separate rebuilds of an answer already
  settled once. The parameter is now `voxel: VoxelSize = UNKNOWN_VOXEL_SIZE`,
  and the header triple is sliced exactly once, by the new
  `VoxelSize.in_plane(voxel_mm)` classmethod, and threaded through from there.
- **Reading or rendering an artifact no longer loads the calculation stack.**
  `fmriqc.analysis` re-exported `analyze` and `build_artifact` eagerly, so
  importing anything from the artifact facade — `load_artifact`, or any of the
  value objects the `fmri-qa-report` package reads — executed the pipeline and
  behind it scikit-image, scipy, nibabel and the metrics. Those two names are
  now resolved on first access instead, and nothing else about the facade
  changes: `import fmriqc_report.cli` in a fresh interpreter fell from 3.7 s to
  2.1 s, and a runtime probe beside the layering scan now holds the seam to
  what actually loads rather than to what the imports say.
- **`spline_nodes`, `poly_degree` and `spline_residuals` drop the `cutoff_s` and
  `degree` parameters nothing ever passed.** `poly_degree(y, tr, cutoff_s)` sat
  `cutoff_s` right next to `tr` — both seconds, both floats — so a swapped
  positional call like `poly_degree(y, 200.0, 2.0)` type-checked and returned
  a degree inflated 100x. No caller anywhere in the tree ever passed
  `cutoff_s` or `degree`; the cutoffs remain exactly what they were, the
  module constants `POLY_CUTOFF_S`, `SPLINE_CUTOFF_S`, and `SPLINE_DEGREE`,
  now read directly instead of threaded through as overridable defaults.
- **`Provenance`'s six identity fields — `scan`, `source`, `created`,
  `core_version`, `tr`, and `n_frames` — are required.** They defaulted to
  `""` and `0`, values the artifact validator rejects outright — so
  `Provenance()` built an object nothing downstream could use. Every real
  constructor already supplied all six; only the useless default is gone.
- **`separate_noise` and `detect_saturation` now take their numeric parameters
  as keyword-only arguments.** `separate_noise(mean_high, mean_low, var_high,
  var_low, ...)` took four same-typed floats whose order is the entire
  meaning: swapping the two means type-checked and inverted `M -> 1/M`,
  producing a negative instability variance and silently taking the
  documented fallback branch, while swapping the two variances was equally
  silent. `detect_saturation(data, slope, inter, trim, ...)` took `slope` and
  `inter` positionally right next to each other — swapped, they still
  type-checked and made the rail test report a clean series, the exact
  failure the module's docstring says must not be possible. Both are
  keyword-only now (arrays and `data` stay positional); every call site
  names its arguments.
- **`trim_count` and `trim_initial` now take `tr` and `trim_sec` as keyword-only
  arguments.** Both are durations in seconds, in an order nothing at a call
  site revealed — and the order is the reverse of the division they perform
  (`trim_sec / tr`). A swap type-checked and returned a plausible wrong frame
  count (with `tr=2.0, trim_sec=5.0` the correct answer is 2, the swapped one
  0), silently shifting every downstream metric and the published `n_trimmed`.
  Keyword-only closes that off; every call site now names both arguments.
- **`ghost_masks`, `ghost_ratio` and `estimate_center_of_mass` no longer invent
  the mask or the axis a caller did not pass.** `ghost_masks` fell back to an
  all-valid mask and `estimate_center_of_mass` to `edge_valid_mask` at its own
  `zero=0.0` default; but an image with a nonzero NIfTI `scl_inter` nulls its
  edge to the intercept, not to `0.0`, so a mask built against `0.0` finds no
  nulled edge on exactly the scans where it matters, and the edge's constant
  line entered the ghost ratio or pulled the centroid with nothing to say so.
  `ghost_ratio` already refused to default its mask for this reason, but still
  defaulted `pe_axis` to `0` — a ratio along an axis nothing measured.
  `valid_mask` is now a required keyword on all three, and `ghost_ratio`'s
  `pe_axis` has no default: pass `QAImages.valid_mask` or
  `edge_valid_mask(image, zero=...)`, and the axis the run resolved.
- **The analysis artifact is written as a netCDF-4 file (`<scan>.qa.nc`), not a
  compressed `.npz`**, so the readers a site already has can open it with
  nothing installed. MATLAB's `ncread`, `ncinfo`, `ncdisp` and `ncreadatt` are
  built in and need no toolbox; R has `ncdf4`; `ncdump` is a shell command;
  netCDF4-python and xarray are one call. A `.npz` reached none of them without
  third-party code — npy-matlab plus a manual unzip on the MATLAB side, RcppCNPy
  numeric-only on the R side — and could never carry the JSON document in a form
  any of them accepted. The arrays keep the dotted names they had
  (`curves.weisskoff.cv`, `images.ghost.pe_ghost`), now declared over shared
  named dimensions (`frame`, `frequency`, `row`, `col`, …) so a reader sees
  which arrays lie along the same axis instead of inferring it from equal
  lengths; every one is deflated and carries a Fletcher-32 checksum over its own
  stored bytes, so damage there is loud rather than a plausible number — damage
  to the container's metadata can still redirect a read, so the checksum makes
  corruption noisy, not the file tamper-proof;
  boolean masks are stored as `uint8` marked in CF style
  (`flag_values`/`flag_meanings`), since netCDF has no boolean type; **every
  scalar the document holds is published as its own global attribute**, a
  nested object flattening into the name (`settings.roi_size`,
  `measurements.snr`, `provenance.tr`, `curves.psf.fwhm`, `images.roi.row0`,
  …), so no reader has to decode JSON at all — a list becomes the vector of its element type,
  so `provenance.voxel_mm` is three doubles and `provenance.matrix` two integers
  in one read, and a list of words one space-separated text, so
  `curves.psf.labels` reads `PE RO`; and the JSON document rides verbatim in the global
  attribute `document`, beside cheap `schema_version`, `title`, `source` and
  `Conventions = "CF-1.10"` globals. A field the document spells `null` — the
  quantity does not apply, or nothing recorded it — has no attribute at all,
  which is what keeps it distinct from a NaN, which says the estimator could not
  resolve it. Provenance text is whatever a file system or a scanner header
  supplied and is written as UTF-8 `NC_CHAR` rather than held to the closed
  vocabularies the string measurements are; a name Python holds as a lone
  surrogate, which has no UTF-8 form at all, rides as its `\udcff` escape in the
  attribute, with the document beside it still spelling the name exactly. No schema
  change — the document's fields and their meanings are identical, only the
  envelope differs — and `load_artifact` still opens every `.qa.npz` an earlier
  build wrote, telling the two containers apart by the file's leading bytes
  rather than by its suffix, since the schema version lives *inside* the
  container and cannot be consulted first. Nothing a site already has on disk is
  orphaned. Three costs, stated plainly. `fmri-qa-core` now depends on
  `netCDF4`, a ~10 MB wheel carrying libhdf5 and libnetcdf — the Unidata C
  library MATLAB, R and Octave are themselves linked against, which is what
  makes "the file opens there" a claim and not a hope. A netCDF-4 file is an
  HDF5 file, and HDF5 takes an advisory lock on every file it opens: on an NFS
  or SMB share whose locking is disabled or broken, a reader may need
  `HDF5_USE_FILE_LOCKING=FALSE` in its environment where a plain read would have
  worked, and this package deliberately does not set it for the whole process.
  And HDF5 carries about 110 KB of fixed metadata for a layout this size, so the
  test phantom's artifact is 135 KB against the `.npz`'s 24 KB; the overhead does
  not grow with the scan (a 128×128×300 acquisition is 441 KB against 230 KB),
  and compression keeps the rest close.

  **Every dimension also carries a coordinate variable**, so a reader gets the
  values along an axis and not just its name: `frequency` and `roi_width` are
  the same numbers as `curves.spectrum_hz` and `curves.weisskoff.roi_sizes`,
  `frame`, `row`, `col`, the two PSF sample axes and the hull's vertices are the
  index along the axis, and the three length-2 label axes name their positions
  in CF flags (`image_axis` "row col", `hull_coord` "x y", and `psf_direction`
  the document's own PSF labels -- "PE RO", or "axis0 axis1" on a run where no
  phase-encode axis resolved) rather than as netCDF strings, which Octave and
  older readers handle poorly. `frame` counts from the *analyzed* series, as every frame index in the
  artifact does, and its `comment` says so — the acquired volume number is the
  index plus `provenance.n_trimmed`. Where an axis's real values cannot be a
  coordinate variable — the seconds along `frame` are `curves.time`, and the PSF
  lags differ by direction and so are 2-D — the variables point at them with a
  CF `coordinates` attribute, so `xr.open_dataset` gives both the index and the
  quantity and `ds["curves.roi_signal"].plot()` draws against seconds. The axes
  are derived when the file is written and never read back, exactly as the
  `measurements.*` attributes are; they are stored unfiltered and contiguous,
  and add 3,322 B to the test phantom's artifact.

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
  consulted first. Archives written by earlier builds load unchanged. The
  container has since changed again — the document now rides in a netCDF global
  attribute (above) — but an `.npz` written in either form still reads.

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
  `<scan>.qa.nc` the same way a batch does. A `PATH` that is not an existing
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

- **`fmri-qa-site` publishes saved artifacts as an offline static report.**
  It creates a fresh directory with an index, per-artifact pages, assets, and a
  versioned `summary.json` inventory; incomplete requests are published and
  return a non-zero status.
- **`InvalidArtifactError` is now reachable from `fmriqc.analysis`.** It is the
  one error `load_artifact` raises, and it was previously only reachable
  through `fmriqc.exceptions` — off limits to `fmri-qa-report`, which may
  import only `fmriqc.analysis` and `fmriqc.types`. A reader of an artifact can
  now catch it by name instead of a blanket `except Exception`.
- **`fmri-qa-hilo --version` now works.** `fmri-qa` and `fmri-qa-import` each
  carried their own copy of the flag and `fmri-qa-hilo` had none, so asking it
  for its version was a usage error. All three now share one, and answer alike.
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
  a single versioned netCDF-4 file.
- `fmri-qa --artifact PATH` saves the artifact for each analyzed scan (a file
  for one scan, a directory of `<scan>.qa.nc` for a batch).
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

- Undefined circular centroids, including uniform positive frames, are now
  excluded per axis from the reference position. Near-zero temporal resultants
  also remain undefined, so cancellation roundoff cannot fabricate displacement.

- RDC panels use finite measurements for plot limits and mark unresolved points.
  Blank scans and curves containing NaN or infinity now render in dashboard and
  physics reports; all-zero curves retain a usable plot range.

- Dashboard reports wrap acquisition metadata and warning notes, and size metric
  tiles to fit their values across multiple rows. Plot heights share the remaining
  space so combined clipping, phantom-mask, and ROI warnings remain visible on a
  single Letter or A4 page without colliding with the footer.

- **Sparse phantoms retain separate background and foreground seeds.** When
  the watershed's intensity quantiles coincide, distinct minimum and maximum
  intensities seed the two classes instead. Small phantoms over zero background
  no longer flood the frame or contaminate the hi/lo core with background;
  constant images return an empty, invalid mask with the existing warning.

- **Imported companions stay with their own series when stems overlap.** NIfTIs
  keep their parsed stems; other companions use the longest matching series stem.
  File destination collisions are refused before any move, even with `--force`.
- **Imported series names stay unique even when a QA name matches a retained
  dcm2niix name.** Colliding series fall back to their original names until all
  collisions are resolved, preventing one scan from silently replacing another.
- **`fmri-qa --artifact ''` is now a usage error instead of a silent no-op.**
  `qa.py` only ever tested `args.artifact` by truthiness, so an empty string
  passed both `if` checks as false: the whole analysis ran, nothing was
  written, and the command exited 0 as if `--artifact` had never been given.
  `--artifact` now carries `arguments.nonempty` as its `type`, so an empty
  value is rejected at parse time with a usage error naming `--artifact`,
  before any scan is read; a run without the flag is unaffected.
- **`fmri-qa-import` no longer prints a traceback when its destination cannot
  be created.** `import_dicom` called `destination.mkdir(parents=True,
  exist_ok=True)` unguarded, so a `-o` pointing at an existing regular file
  raised a bare `FileExistsError` that `import_main` did not catch. The
  `mkdir` is now wrapped as `ConversionError("destination", ...)`, and
  `import_main` catches broadly like every other command, so the failure
  prints one `ERROR: ...` line to stderr and exits 1.
- **A BIDS sidecar whose `AcquisitionDate` is a JSON number no longer crashes
  the load.** `load.metadata` built the acquisition datetime by joining
  `AcquisitionDate` and `AcquisitionTime` with `" ".join(...)`, converting the
  time to text first but not the date — so a sidecar with `"AcquisitionDate":
  20260909` (unquoted, as some writers emit it) raised a bare
  `TypeError: sequence item 0: expected str instance, int found` instead of
  loading. The date is now converted the same way its neighbour already is;
  a sidecar value that comes through unquoted is still parsed, the same
  latitude `_optional_text` already gives a numeric serial number.
- **Importing `fmriqc_report` no longer switches the matplotlib backend to
  `Agg`.** The package called `matplotlib.use("Agg")` at import time, silently
  overriding whatever backend the importing process — a notebook's inline
  backend, say — had already chosen. Rendering never needed it: panels build
  `matplotlib.figure.Figure` objects directly and save them with `fig.savefig`,
  with no `pyplot` involved.
- **`import_dicom` now raises `InvalidChoiceError` for a `names` or `anonymize`
  value outside its permitted set.** It was the one public entry point that
  took closed-set string options with no guard of its own — a bad `names`
  reached `assert_never` and came back as a bare `AssertionError`, and a bad
  `anonymize` reached `dcm2niix._BA` and came back as a bare `KeyError`,
  either way escaping `except FmriqcError`. Both are now checked before
  anything is staged or dcm2niix is even looked up. The CLI was never
  affected — `--names`/`--anonymize` already restrict both flags with
  `choices=`.
- **`validate_artifact` now checks that a duplicated fact agrees with itself.**
  Two groups of published fields are derived copies of others — `clipped_any`/
  `clipped_kept` from the clipping counts, and the None-ness of `fwhm_pe`/
  `fwhm_ro` from `pe_axis` — and nothing compared them. A hand-edited or
  foreign document could carry `n_clipped_kept: 500` beside `clipped_kept:
  false`, and it loaded anyway: the CLI table dropped its "!" flag, and the
  PDF report either said nothing about the clipping (if `clipped_any` was
  also left false) or printed a "pre-SS only" line for clipping that was
  really in the analyzed data. Such a document now loads only if its
  duplicated fields agree; a self-contradictory one is refused.
- **`save_artifact` now checks the one field `load_artifact` checks first.**
  It already held a written artifact to the reader's other checks, but let any
  `schema_version` through uncaught — 99, 0, a float, a string, even `True` —
  so a bad value was written successfully, replaced whatever valid archive
  already stood at the path, and was refused only when something later tried
  to read it back. A `schema_version` that is not exactly the version this
  build writes is now refused before anything is written, the same way every
  other mismatch between the artifact and the reader's contract already was.
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
  a truncated artifact in the archive. It writes a temporary file beside the
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

- **`QAImages.pe_axis`.** Nothing read it since `validate_qa_run` began
  returning the resolved axis; the narrowing (`load.pe_axis.in_plane`) still
  happens, once, in `validate_qa_run`.
- **`OutlierResult.mean_fraction`.** Nothing read it: the artifact publishes
  the worst frame, `max_fraction` (as `outlier_max_pct`) and `worst_volume`,
  never the mean across frames.
- `MissingSidecarError`: a missing sidecar is a warning now, not an error.
- `ghost_top_ratio`, `acr_ghosting_ratio`, and `phase_encode_axis`; their
  measurements come from `GhostResult`, and `QAMetrics` carries that result
  instead of four loose percentages.

- `fmri-qa --pdf`, `--pdf-tier`, `--pdf-cover`, and `--pdf-appendix`. Rendering
  moved to `fmri-qa-report`, whose equivalents are `--pdf`, `--tier`, `--cover`,
  and `--appendix`; producing a report is now two commands.
