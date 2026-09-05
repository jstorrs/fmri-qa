"""The per-metric catalog: tiles and characterization share one source."""

from fmriqc_report import content


def test_tiles_and_characterization_share_labels_and_values(artifact) -> None:
    m = artifact.measurements
    tiles = content.metric_tiles(m)
    rows = content.characterization_rows(m)
    # Same metrics, same order, same formatted values -- one catalog drives both.
    assert [label for label, _ in tiles] == [doc.label for doc, _ in rows]
    assert [value for _, value in tiles] == [value for _, value in rows]


def test_every_metric_doc_is_documented(artifact) -> None:
    m = artifact.measurements
    for doc in content.METRIC_DOCS:
        assert doc.label and doc.definition and doc.method
        assert doc.fmt(m)  # the formatter returns a non-empty string
