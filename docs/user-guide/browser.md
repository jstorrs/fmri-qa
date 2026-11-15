# In the browser

The [browser version of fmri-qa](https://jstorrs.github.io/fmri-qa/app/) is a
single HTML file that converts and analyzes DICOM on the user's own computer.
Nothing is uploaded, and the page makes no network request once it has loaded.
It performs the same analysis as the installed commands.

The page can be opened from the website, or the file (about 67 MB) can be saved
and opened locally. A saved copy works without a network connection, which suits
a scanner console or a hospital computer on which nothing can be installed.
Chrome and Firefox are tested. Safari is not.

## Procedure

1. **Wait for Python to start.** Startup takes about a minute, and the page
   reports each stage. DICOM can be added in the meantime.
2. **Add DICOM.** Use "Open folder" or "Open files" (DICOM files or `.zip`
   archives), or drop files, folders or archives onto the page. The page lists
   what it found by patient, study and series, together with the files it
   skipped.
3. **Select the series** and press **Run QA on selected**. Each series is
   converted with dcm2niix and analyzed in turn. **Cancel** stops a conversion
   immediately. An analysis that is already running completes and keeps its
   report, and no further series is started.
4. **Review the results.** The table has one row per series. A finished series
   can display its report on the page, and each of its files can be downloaded:
   the NIfTI, its sidecar, the HTML report, and the numerical results as JSON
   (`<series>.qa.json`). The Zip button on a row saves the files of that series
   together, and **Download all** saves every series as a single `.zip`.

Series are named as {doc}`fmri-qa-run <run-output>` names them. Patient
identifiers are omitted from the sidecar and the dates are retained, as under
`--anonymize pii`. The analysis uses the default settings.

The JSON record is the document that {doc}`fmri-qa --json <fmri-qa>` prints for
the same scan. The browser cannot write the netCDF
{doc}`analysis file <analysis-file>` (`.qa.nc`), which requires the installed
commands.

## Large series

The page converts and analyzes one series at a time, so the size of the largest
series matters more than the size of the study. A series too large for the
browser's memory fails with "dcm2niix crashed, probably out of memory", and the
remaining series still run. If Python itself exhausts its memory, the page
reports this and must be reloaded.

In Firefox and Safari, "Download all" assembles the archive in memory, and the
page asks for confirmation when the archive would exceed 2 GB. Chrome writes it
directly to disk.

## Identifying the version

The footer gives the version, the commit from which the page was built and the
date of that commit, and it links to the latest version. Comparing it with the
footer of the [published page](https://jstorrs.github.io/fmri-qa/app/) shows
whether a saved copy is out of date.

"About & licences" in the footer lists the licences of every component bundled
in the file. A copy passed to others should be left unmodified.
