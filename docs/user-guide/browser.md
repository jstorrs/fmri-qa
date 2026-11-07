# In the browser

[Open fmri-qa in your browser](https://jstorrs.github.io/fmri-qa/app/). It is
one HTML file that converts and analyzes DICOM on your own computer. Nothing is
uploaded: the page makes no network request once it has loaded. It runs the
same analysis as the installed commands.

You can open it from the web page, or save the file (about 67 MB) and
double-click it. A saved copy works with no network, which suits a scanner
console or a hospital machine where nothing can be installed. Chrome and
Firefox are tested. Safari is not.

## Running QA

1. **Wait for Python to start.** It takes about a minute, and the page lists
   each stage. You can add DICOM meanwhile.
2. **Add DICOM.** Use "Open folder", "Open files" (DICOM files or `.zip`
   archives), or drop files, folders or archives on the page. The page lists
   what it found by patient, study and series, with the files it skipped.
3. **Choose the series** and press **Run QA on selected**. Each series is
   converted with dcm2niix and analyzed in turn. **Cancel** stops a conversion
   at once. An analysis already running finishes and keeps its report, and
   nothing new starts.
4. **Read the results.** The table has one row per series. A finished series
   can show its report on the page, and each file can be downloaded: the
   NIfTI, its sidecar, the HTML report, and the numbers as JSON
   (`<series>.qa.json`). A row's Zip button saves that series' files together,
   and **Download all** saves every series as one `.zip`.

The series are named as {doc}`fmri-qa-run <run-output>` names them. Patient
identifiers are left out of the sidecar and the dates are kept, as with
`--anonymize pii`. The analysis uses the default settings.

The JSON record is the document {doc}`fmri-qa --json <fmri-qa>` prints for that
scan. The browser cannot write the netCDF {doc}`analysis file <artifact>`
(`.qa.nc`). For that, run the installed commands.

## Large series

The page converts and analyzes one series at a time, so a study's size matters
less than its largest series. A series too large for the browser's memory fails
with "dcm2niix crashed, probably out of memory", and the others still run. If
Python itself runs out of memory, the page says so and has to be reloaded.

In Firefox and Safari, "Download all" builds the archive in memory, and the page
asks first when it would be over 2 GB. Chrome writes it straight to disk.

## Which version you have

The footer names the version, the commit it was built from and that commit's
date, and links to the latest version. Compare it with the footer of the
[published page](https://jstorrs.github.io/fmri-qa/app/) to see whether a saved
copy is out of date.

"About & licences" in the footer lists the licences of everything the file
bundles. If you pass the file on, keep it as it is.
