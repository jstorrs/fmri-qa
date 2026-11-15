# fmri-qa

fmri-qa quantifies the stability of an MRI scanner during functional imaging
from a phantom time series. It implements the Glover/FBIRN stability protocol
(Friedman & Glover, 2006), which reports the signal-to-noise ratio (SNR), the
signal-to-fluctuation-noise ratio (SFNR), the Weisskoff radius of decorrelation,
drift, and fluctuation. To these it adds measures of Nyquist ghosting, receiver
clipping, outlier volumes and spikes, apparent motion caused by gradient
heating, and noise smoothness. Each series yields a self-contained HTML report,
and its numerical results are saved in a file that MATLAB, R, Python, or a trend
database can read.

The analysis can also be
**[run in a web browser](https://jstorrs.github.io/fmri-qa/app/)** with no
installation. The page accepts DICOM, lists the series it contains, and converts
and analyzes the selected series on the user's own computer. No data leave that
computer, and the page can be saved and used offline. The source code is
[on GitHub](https://github.com/jstorrs/fmri-qa).

```{toctree}
:hidden:

user-guide/index
api/index
```

## Organization of the documentation

- **Running an analysis.** A phantom series can be analyzed
  {doc}`in the browser </user-guide/browser>`,
  {doc}`from the desktop panel </user-guide/panel>`, or
  {doc}`from a terminal </user-guide/fmri-qa-run>`. The panel and the commands
  require {doc}`installation </user-guide/install>`.
- **Definitions of the measurements.** {doc}`/user-guide/analyses/index` lists
  every measurement, and the page for each analysis gives its method and
  equations.
- **Contents of the report.** {doc}`/user-guide/report-page` describes each
  section and figure, the contents of the HTML file, and what a website that
  embeds it must permit.
- **Longitudinal tracking.** {doc}`/user-guide/fmri-qa` writes JSON suitable for
  a trend database, and {doc}`/user-guide/analysis-file` shows how to open an
  analysis file in MATLAB, R or Python.
- **Use from Python.** {doc}`/user-guide/developers` introduces the packages,
  and the {doc}`API reference </api/index>` documents every public name.

## Reference

- Friedman L, Glover GH. Report on a multicenter fMRI quality assurance
  protocol. *J Magn Reson Imaging* 2006;23:827–839.
  [doi:10.1002/jmri.20583](https://doi.org/10.1002/jmri.20583)
