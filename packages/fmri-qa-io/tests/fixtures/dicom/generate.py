"""Regenerate the synthetic DICOM studies the import tests convert.

Committed rather than generated at test time because pydicom is not a
dependency of either distribution (it lives in the workspace's `notebooks`
group), and a test that skipped without it would skip everywhere that matters.
The files are synthetic: disc phantoms with a little noise. Nothing came from a
scanner and no patient exists (PatientName is `QA^PHANTOM`).

Two studies are committed, both from this script:

* `dicom/`, the defaults: 16x16, two slices, two volumes, two series. Too short
  to analyze (`MIN_ANALYSIS_FRAMES` after the warm-up trim), which is fine for
  the naming and conversion tests it serves. Its UIDs came from random
  `generate_uid()` calls, so **regenerating it with the defaults changes every
  byte of the UIDs**; do not, unless the fixture has to change.
* `dicom-qa/`, one series (2), 48x48, three slices, twelve volumes at TR 2 s:
  converts *and* analyzes with the default settings (48 wide so the default
  21x21 ROI fits inside the disc; 32 did not). With `--seed` the UIDs are
  derived from the seed and the noise from it too, so regenerating is
  byte-identical for the same pydicom and numpy versions.

The two series of `dicom/` make the importer prove:

* series **2** and **11** sort wrongly under dcm2niix's unpadded `%s` and
  rightly under the zero-padded QA name;
* descriptions `QA_EPI_ISO` and `QA EPI 32ch (rep)`: one needs no sanitizing,
  and one has the spaces and parentheses of a real protocol name;
* distinct `SeriesTime`s under one `StudyTime`, which dcm2niix's `%t` cannot
  express (it is the study's time, the same for both).

Run from the workspace root:

    uv run --group notebooks python \\
        packages/fmri-qa-io/tests/fixtures/dicom/generate.py \\
        --seed 1 --dim 48 --slices 3 --volumes 12 \\
        --series 2:QA_EPI_ISO:143012.500000 \\
        --out packages/fmri-qa-io/tests/fixtures/dicom-qa
"""

import argparse
from collections.abc import Sequence
from pathlib import Path

import numpy as np
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

HERE = Path(__file__).parent

# (series number, description, series time)
SERIES = (
    (2, "QA_EPI_ISO", "143012.500000"),
    (11, "QA EPI 32ch (rep)", "145533.250000"),
)


def build(
    out: Path = HERE,
    *,
    dim: int = 16,
    n_slice: int = 2,
    n_vol: int = 2,
    series: Sequence[tuple[int, str, str]] = SERIES,
    seed: int | None = None,
) -> None:
    """Write the study under `out`, one folder per series.

    With `seed` None the UIDs are random and the noise is the original
    per-slice sequence, which is how `dicom/` was made. With a seed both are
    derived from it, so the same arguments give the same bytes.
    """
    study_uid = _uid(seed, "study")
    for number, description, series_time in series:
        series_uid = _uid(seed, "series", number)
        for volume in range(n_vol):
            for index in range(n_slice):
                ds = _instance(
                    dim, study_uid, series_uid, number, description, series_time
                )
                ds.InstanceNumber = volume * n_slice + index + 1
                ds.SOPInstanceUID = _uid(seed, "instance", number, ds.InstanceNumber)
                ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
                ds.AcquisitionNumber = volume + 1
                ds.ImagePositionPatient = [
                    -dim * 1.5,
                    -dim * 1.5,
                    float(index) * 4.0,
                ]
                ds.SliceLocation = float(index) * 4.0
                ds.PixelData = _phantom(dim, seed, number, volume, index).tobytes()

                path = out / f"series{number:03d}" / f"{ds.InstanceNumber:04d}.dcm"
                path.parent.mkdir(parents=True, exist_ok=True)
                ds.save_as(path, enforce_file_format=True)


def _uid(seed: int | None, *parts: object) -> str:
    """A fresh UID, or one derived from `seed` and `parts` when seeded."""
    if seed is None:
        return generate_uid()
    # One separated string: pydicom joins `entropy_srcs` with nothing, so
    # separate parts would let ("instance", 2, 11) and ("instance", 21, 1) collide.
    return generate_uid(entropy_srcs=[":".join(map(str, (seed, *parts)))])


def _phantom(
    dim: int, seed: int | None, number: int, volume: int, index: int
) -> np.ndarray:
    """A bright disc on a dim background, with a little noise."""
    rng = np.random.default_rng(
        volume * 10 + index if seed is None else [seed, number, volume, index]
    )
    y, x = np.ogrid[:dim, :dim]
    disc = ((x - dim / 2) ** 2 + (y - dim / 2) ** 2) < (dim / 3) ** 2
    return (np.where(disc, 1000, 20) + rng.integers(0, 10, (dim, dim))).astype(
        np.uint16
    )


def _instance(
    dim: int,
    study_uid: str,
    series_uid: str,
    number: int,
    description: str,
    series_time: str,
) -> Dataset:
    """One MR image instance, minus the per-slice fields the caller sets.

    Those are the instance number and UID, the position and the pixels.
    """
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.4"
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.SOPClassUID = ds.file_meta.MediaStorageSOPClassUID

    ds.PatientName = "QA^PHANTOM"
    ds.PatientID = "QA001"
    ds.Modality = "MR"
    ds.Manufacturer = "SIEMENS"
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.StudyID = "1"
    ds.StudyDate = ds.SeriesDate = ds.AcquisitionDate = "20260909"
    ds.StudyTime = "142500.000000"  # the study's time: shared by both series
    ds.SeriesTime = ds.AcquisitionTime = series_time
    ds.SeriesNumber = number
    ds.SeriesDescription = description
    ds.ProtocolName = "ep2d_bold_qa"
    ds.SequenceName = f"epfid2d1_{dim}"

    ds.MRAcquisitionType = "2D"
    ds.RepetitionTime = 2000.0
    ds.EchoTime = 30.0
    ds.FlipAngle = 77.0
    ds.InPlanePhaseEncodingDirection = "COL"
    ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    ds.SliceThickness = 4.0
    ds.SpacingBetweenSlices = 4.0
    ds.PixelSpacing = [3.0, 3.0]

    ds.Rows = ds.Columns = dim
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = 16
    ds.BitsStored = 12
    ds.HighBit = 11
    ds.PixelRepresentation = 0  # unsigned, as a magnitude reconstruction is
    return ds


def _series_arg(text: str) -> tuple[int, str, str]:
    """Parse `NUMBER:DESCRIPTION:SERIESTIME`."""
    number, description, series_time = text.split(":", 2)
    return int(number), description, series_time


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, default=HERE)
    parser.add_argument("--dim", type=int, default=16)
    parser.add_argument("--slices", type=int, default=2)
    parser.add_argument("--volumes", type=int, default=2)
    parser.add_argument(
        "--series",
        type=_series_arg,
        action="append",
        metavar="NUMBER:DESCRIPTION:SERIESTIME",
        help="repeatable; default is the two series in SERIES",
    )
    parser.add_argument(
        "--seed", type=int, default=None, help="make UIDs and noise reproducible"
    )
    args = parser.parse_args()
    build(
        args.out,
        dim=args.dim,
        n_slice=args.slices,
        n_vol=args.volumes,
        series=args.series or SERIES,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
