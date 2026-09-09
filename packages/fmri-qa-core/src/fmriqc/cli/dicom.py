"""`fmri-qa-import`: convert a DICOM directory into QA-ready NIfTI.

A separate command rather than a subcommand of `fmri-qa`, following
`fmri-qa-hilo`: `fmri-qa` takes scan paths as its positional arguments, so
turning it into a subcommand parser would change how every existing invocation
is written.

What it adds over running dcm2niix by hand is two things it is easy to get
wrong: the flags that keep a series checkable (`convert.dcm2niix`, where `-l o`
decides whether the saturation check can see an ADC rail at all) and names that
sort and read (`convert.naming`). Everything else dcm2niix does it still does —
`--filename` keeps its template language, and `--dcm2niix-arg` passes anything
through.
"""

import argparse
import sys
import warnings
from collections.abc import Sequence
from pathlib import Path

import fmriqc as q
from fmriqc.convert.dcm2niix import DEFAULT_TEMPLATE
from fmriqc.convert.session import ImportResult, import_dicom

from .arguments import positive_int, print_warnings


class _PrintVersion(argparse.Action):
    """`--version`, resolved on use rather than when the parser is built."""

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: object,
        option_string: str | None = None,
    ) -> None:
        print(f"{parser.prog} {q.core_version()}")
        parser.exit()


def _parser() -> argparse.ArgumentParser:
    """The command line this command accepts."""
    parser = argparse.ArgumentParser(
        prog="fmri-qa-import",
        description="Convert a DICOM directory to QA-ready NIfTI with dcm2niix, "
        "keeping the scanner's stored integers (which the saturation check "
        "needs) and naming each series by date, time, series number and "
        "description.",
    )
    parser.add_argument(
        "source", help="Directory of DICOM files (searched recursively)"
    )
    parser.add_argument(
        "-o",
        "--out",
        metavar="DIR",
        default=None,
        help="Where to write the NIfTI (default: ./<source name>_nifti). "
        "Created if missing; an existing file it would overwrite stops the "
        "import unless --force.",
    )
    parser.add_argument(
        "--names",
        choices=q.NAME_STYLES,
        default="qa",
        help="'qa': <date>_<time>_s<NNN>_<description>, which sorts "
        "chronologically and pads the series number. 'dcm2niix': whatever "
        "--filename produced. Default: qa.",
    )
    # argparse %-formats every help string, and the template is all %-codes,
    # so it has to reach the help already escaped.
    shown_template = DEFAULT_TEMPLATE.replace("%", "%%")
    parser.add_argument(
        "--filename",
        metavar="TEMPLATE",
        default=DEFAULT_TEMPLATE,
        help=f"dcm2niix -f template (default: {shown_template}). With "
        "--names qa this is only the fallback for a series whose sidecar "
        "cannot name it; with --names dcm2niix it is the name.",
    )
    parser.add_argument(
        "--anonymize",
        choices=q.ANONYMIZE_MODES,
        default="pii",
        help="Sidecar content: 'pii' strips the patient and keeps the dates "
        "(default, and what 'qa' names need), 'all' strips the dates too, "
        "'none' keeps everything.",
    )
    parser.add_argument(
        "--no-compress",
        action="store_true",
        help="Write .nii instead of .nii.gz.",
    )
    parser.add_argument(
        "--depth",
        type=positive_int,
        default=5,
        help="Sub-directory levels of SOURCE to search (default: 5).",
    )
    parser.add_argument(
        "--dcm2niix",
        metavar="PATH",
        default=None,
        help="dcm2niix to run (default: the bundled binary from the 'dicom' "
        "extra, else the first on PATH).",
    )
    parser.add_argument(
        "--dcm2niix-arg",
        metavar="ARG",
        action="append",
        default=[],
        dest="passthrough",
        help="Extra argument for dcm2niix, repeatable and passed last so it "
        "wins. A value starting with '-' needs the '=' form, which is most of "
        "them: --dcm2niix-arg=-i --dcm2niix-arg=y",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite files already in the output directory.",
    )
    parser.add_argument(
        "--log",
        action="store_true",
        help="Print everything dcm2niix said, not just the summary.",
    )
    parser.add_argument("--version", action=_PrintVersion, nargs=0)
    return parser


def _destination(source: str, out: str | None) -> Path:
    """Where the NIfTI goes: `--out`, else `<source name>_nifti` here.

    Derived from the source rather than defaulting to the working directory, so
    the common one-argument call puts a session's series together in a directory
    named after it instead of scattering them where the command was run.
    """
    if out is not None:
        return Path(out)
    return Path(f"{Path(source).resolve().name}_nifti")


def _print_listing(result: ImportResult, destination: Path, *, renaming: bool) -> None:
    """One row per series: number, when it ran, and the file it is now in."""
    print(f"{'series':>6}  {'acquired':<19}  file")
    for entry in result.series:
        acquired = (entry.acquired or "").replace("T", " ")[:19]
        number = "?" if entry.series is None else str(entry.series)
        print(f"{number:>6}  {acquired:<19}  {entry.path.name}")
    # `renamed_from` is dcm2niix's stem when the series was renamed, so the
    # ones that kept it are the Nones. Only worth saying under --names qa,
    # where a file left with dcm2niix's name is the exception `naming.plan`
    # made for a reason the reader can act on -- an uninformative sidecar, or
    # two series that would have shared a name. Under --names dcm2niix every
    # file keeps that name by request, and saying so would be noise.
    kept = [entry for entry in result.series if entry.renamed_from is None]
    if renaming and kept:
        print(
            f"# {len(kept)} of {len(result.series)} series kept dcm2niix's name: "
            f"{', '.join(entry.path.name for entry in kept)}",
            file=sys.stderr,
        )
    print(f"# {len(result.series)} series -> {destination}")
    # The glob names the suffix actually written, so the line can be pasted
    # whether or not --no-compress was used.
    suffix = "".join(result.series[0].path.suffixes[-2:])
    print(f"# analyze with:  fmri-qa {destination}/*{suffix}")


def import_main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    destination = _destination(args.source, args.out)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            result = import_dicom(
                args.source,
                destination,
                binary=args.dcm2niix,
                names=args.names,
                template=args.filename,
                compress=not args.no_compress,
                anonymize=args.anonymize,
                depth=args.depth,
                extra=args.passthrough,
                force=args.force,
            )
        except q.ConversionError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            print_warnings(caught, Path(args.source).name)
            return 1
    print_warnings(caught, Path(args.source).name)

    if args.log:
        print(result.log, file=sys.stderr)
    tool = result.tool_version or "version unknown"
    print(f"# dcm2niix {tool} ({result.binary})")
    if not result.series:
        print(f"ERROR: no DICOM series converted from {args.source}", file=sys.stderr)
        return 1
    _print_listing(result, destination, renaming=args.names == "qa")
    return 0
