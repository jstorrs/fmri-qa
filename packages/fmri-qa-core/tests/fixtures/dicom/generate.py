"""Regenerate the miniature DICOM study `test_import_real_dicom.py` imports.

Committed rather than generated at test time because pydicom is not a dependency
of either distribution -- it lives in the workspace's `notebooks` group -- and a
test that skipped whenever it was absent would skip everywhere that matters. The
files it writes are synthetic: a 16x16 disc phantom, two slices, two volumes,
two series. Nothing here came from a scanner and no patient exists.

The two series are chosen for what they make the importer prove:

* series **2** and **11**, so a listing sorts them in the wrong order under
  dcm2niix's unpadded `%s` and the right one under the zero-padded QA name;
* descriptions `QA_EPI_ISO` and `QA EPI 32ch (rep)`, so one needs no
  sanitizing and one has the spaces and parentheses a real protocol name
  carries;
* distinct `SeriesTime`s under one `StudyTime`, which is the difference
  dcm2niix's `%t` cannot express (it is the study's time, the same for both).

Run from the workspace root, after `make sync-notebooks`:

    uv run python packages/fmri-qa-core/tests/fixtures/dicom/generate.py
"""

from pathlib import Path

import numpy as np
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

HERE = Path(__file__).parent
DIM, N_SLICE, N_VOL = 16, 2, 2

# (series number, description, series time)
SERIES = (
    (2, "QA_EPI_ISO", "143012.500000"),
    (11, "QA EPI 32ch (rep)", "145533.250000"),
)


def build() -> None:
    """Write the study under this directory, one folder per series."""
    study_uid = generate_uid()
    for number, description, series_time in SERIES:
        series_uid = generate_uid()
        for volume in range(N_VOL):
            for index in range(N_SLICE):
                ds = _instance(study_uid, series_uid, number, description, series_time)
                ds.InstanceNumber = volume * N_SLICE + index + 1
                ds.AcquisitionNumber = volume + 1
                ds.ImagePositionPatient = [-24.0, -24.0, float(index) * 4.0]
                ds.SliceLocation = float(index) * 4.0
                ds.PixelData = _phantom(volume, index).tobytes()

                out = HERE / f"series{number:03d}" / f"{ds.InstanceNumber:04d}.dcm"
                out.parent.mkdir(parents=True, exist_ok=True)
                ds.save_as(out, enforce_file_format=True)


def _phantom(volume: int, index: int) -> np.ndarray:
    """A bright disc on a dim background, with a little noise."""
    rng = np.random.default_rng(volume * 10 + index)
    y, x = np.ogrid[:DIM, :DIM]
    disc = ((x - DIM / 2) ** 2 + (y - DIM / 2) ** 2) < (DIM / 3) ** 2
    return (np.where(disc, 1000, 20) + rng.integers(0, 10, (DIM, DIM))).astype(
        np.uint16
    )


def _instance(
    study_uid: str, series_uid: str, number: int, description: str, series_time: str
) -> Dataset:
    """One MR image instance, minus the per-slice fields the caller sets."""
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.4"
    ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.SOPClassUID = ds.file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID

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
    ds.SequenceName = "epfid2d1_16"

    ds.MRAcquisitionType = "2D"
    ds.RepetitionTime = 2000.0
    ds.EchoTime = 30.0
    ds.FlipAngle = 77.0
    ds.InPlanePhaseEncodingDirection = "COL"
    ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    ds.SliceThickness = 4.0
    ds.SpacingBetweenSlices = 4.0
    ds.PixelSpacing = [3.0, 3.0]

    ds.Rows = ds.Columns = DIM
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = 16
    ds.BitsStored = 12
    ds.HighBit = 11
    ds.PixelRepresentation = 0  # unsigned, as a magnitude reconstruction is
    return ds


if __name__ == "__main__":
    build()
