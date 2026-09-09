"""The per-metric catalog: tiles and characterization share one source."""

from fmriqc_report import content


def test_tiles_and_characterization_share_labels_and_values(artifact) -> None:
    m = artifact.measurements
    tiles = content.metric_tiles(m)
    rows = content.characterization_rows(m)
    # Same metrics, same order, same formatted values -- one catalog drives both.
    assert [label for label, _ in tiles] == [doc.label for doc, _ in rows]
    assert [value for _, value in tiles] == [value for _, value in rows]


def test_methods_describe_the_implemented_order_of_operations() -> None:
    """The catalog's method text must name what the code does, not a synonym.

    SFNR averages voxelwise ratios (the ROI-mean form is `fluct`), the ghost
    denominator is the matched signal region, and ACRg is an absolute
    difference; each of these once read as the other textbook form.
    """
    by_label = {doc.label: doc for doc in content.METRIC_DOCS}
    assert "per voxel" in by_label["SFNR"].method
    assert "ROI mean of those ratios" in by_label["SFNR"].method
    assert "ROI-mean series" in by_label["fluct"].method
    assert "matched signal region" in by_label["ghost"].method
    assert "|ghost - RO|" in by_label["ACRg"].method
    assert "at the full ROI" in by_label["RDC"].method


def test_every_metric_doc_is_documented(artifact) -> None:
    m = artifact.measurements
    for doc in content.METRIC_DOCS:
        assert doc.label and doc.definition and doc.method
        assert doc.fmt(m)  # the formatter returns a non-empty string


def test_motn_and_com_tiles_carry_the_displacement_unit(
    artifact, bare_artifact
) -> None:
    """`motn`/`com` render their unit exactly as `fwhm` already does.

    `artifact` has a known voxel size and reports mm; `bare_artifact` has no
    sidecar metadata at all and falls back to voxels -- the same "mm when known,
    else voxels" rule `_fwhm_label` applies, read off `displacement_unit`.
    """
    by_label = {doc.label: doc for doc in content.METRIC_DOCS}
    m = artifact.measurements
    assert by_label["motn"].fmt(m) == f"{m.max_translation:.2f}mm"
    assert by_label["com"].fmt(m) == f"{m.max_com_displacement:.2f}mm"

    bare = bare_artifact.measurements
    assert by_label["motn"].fmt(bare) == f"{bare.max_translation:.2f}vox"
    assert by_label["com"].fmt(bare) == f"{bare.max_com_displacement:.2f}vox"
