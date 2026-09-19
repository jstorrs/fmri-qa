#!/usr/bin/env bash
# Usage: ./scripts/test_fbirn_site.sh [DICOM_DIRECTORY]
# Requires: uv sync --all-packages
#
# Imports a DICOM series, analyses it, and renders every HTML output: the
# static site (fmri-qa-site) and one standalone report per artifact
# (fmri-qa-report --html). Then checks that each run page really is a single
# self-contained file.
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
source_dir=${1:-/scratch/usbstick/coils/fbirn_64ch_run2}

if (( $# > 1 )) || [[ ! -d "$source_dir" ]]; then
    printf 'Usage: %s [DICOM_DIRECTORY]\nInput must be an existing directory.\n' "$0" >&2
    exit 1
fi

run() {
    uv run --project "$repo_root" --all-packages "$@"
}

# A run page must open from a double-click: no stylesheet link, no script, and
# every figure embedded rather than fetched from a sibling file.
check_self_contained() {
    local page=$1
    if grep -qE '<link|<script' "$page"; then
        printf 'FAIL: %s references an external stylesheet or script\n' "$page" >&2
        return 1
    fi
    local images embedded
    images=$(count_matches '<img[^>]* src="' "$page")
    embedded=$(count_matches '<img[^>]* src="data:image/svg\+xml;base64,' "$page")
    if (( images == 0 || images != embedded )); then
        printf 'FAIL: %s embeds %d of its %d figures\n' "$page" "$embedded" "$images" >&2
        return 1
    fi
}

# grep exits 1 on no match, which pipefail would turn into a script failure.
count_matches() {
    { grep -oE -- "$1" "$2" || true; } | wc -l
}

# A fresh directory makes repeat runs safe and satisfies fmri-qa-site's contract.
mkdir -p "$repo_root/build"
output_dir=$(mktemp -d "$repo_root/build/fbirn-site.XXXXXX")
# mktemp makes the directory private; the site inside is meant to be served.
chmod 755 "$output_dir"
printf 'Writing results to %s\n' "$output_dir"

run fmri-qa-import "$source_dir" --out "$output_dir/nifti"

shopt -s nullglob
scans=("$output_dir/nifti/"*.nii "$output_dir/nifti/"*.nii.gz)
if (( ${#scans[@]} == 0 )); then
    printf 'No NIfTI scans were produced in %s/nifti\n' "$output_dir" >&2
    exit 1
fi

mkdir "$output_dir/artifacts"
run fmri-qa "${scans[@]}" --artifact "$output_dir/artifacts"

artifacts=("$output_dir/artifacts/"*.qa.nc)
if (( ${#artifacts[@]} == 0 )); then
    printf 'No artifacts were produced in %s/artifacts\n' "$output_dir" >&2
    exit 1
fi

run fmri-qa-site "${artifacts[@]}" --output "$output_dir/site"

# --html renders one artifact to one file, so standalone reports go one by one.
mkdir "$output_dir/reports"
for artifact in "${artifacts[@]}"; do
    name=$(basename -- "$artifact" .qa.nc)
    run fmri-qa-report "$artifact" --html "$output_dir/reports/$name.html"
done

failures=0
for page in "$output_dir/reports/"*.html "$output_dir/site/runs/"*/index.html; do
    check_self_contained "$page" || failures=$((failures + 1))
done
for required in index.html summary.json assets/report.css; do
    if [[ ! -f "$output_dir/site/$required" ]]; then
        printf 'FAIL: site is missing %s\n' "$required" >&2
        failures=$((failures + 1))
    fi
done
# A site run is the one page and nothing beside it.
extras=$(find "$output_dir/site/runs" -mindepth 2 ! -name index.html)
if [[ -n "$extras" ]]; then
    printf 'FAIL: unexpected files beside the run pages:\n%s\n' "$extras" >&2
    failures=$((failures + 1))
fi
if (( failures > 0 )); then
    printf '\n%d check(s) failed; outputs kept in %s\n' "$failures" "$output_dir" >&2
    exit 1
fi

printf '\nAll run pages are self-contained.\n'
printf 'Site index:         %s/site/index.html\n' "$output_dir"
printf 'Standalone reports: %s/reports/\n' "$output_dir"
