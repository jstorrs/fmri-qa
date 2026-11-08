#!/usr/bin/env bash
# Usage: ./scripts/test_fbirn_report.sh [DICOM_DIRECTORY]
# Requires: uv sync --all-packages
#
# Imports a DICOM series, analyses it, renders one standalone HTML report per
# analysis, and checks each is a single self-contained file.
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

# A fresh directory makes repeat runs safe.
mkdir -p "$repo_root/build"
output_dir=$(mktemp -d "$repo_root/build/fbirn-report.XXXXXX")
printf 'Writing results to %s\n' "$output_dir"

run fmri-qa-import "$source_dir" --out "$output_dir/nifti"

shopt -s nullglob
scans=("$output_dir/nifti/"*.nii "$output_dir/nifti/"*.nii.gz)
if (( ${#scans[@]} == 0 )); then
    printf 'No NIfTI scans were produced in %s/nifti\n' "$output_dir" >&2
    exit 1
fi

mkdir "$output_dir/analyses"
run fmri-qa "${scans[@]}" --analysis-file "$output_dir/analyses"

analyses=("$output_dir/analyses/"*.qa.nc)
if (( ${#analyses[@]} == 0 )); then
    printf 'No analyses were produced in %s/analyses\n' "$output_dir" >&2
    exit 1
fi

# --html renders one analysis to one file, so standalone reports go one by one.
mkdir "$output_dir/reports"
for analysis in "${analyses[@]}"; do
    name=$(basename -- "$analysis" .qa.nc)
    run fmri-qa-report "$analysis" --html "$output_dir/reports/$name.html"
done

failures=0
for page in "$output_dir/reports/"*.html; do
    check_self_contained "$page" || failures=$((failures + 1))
done
if (( failures > 0 )); then
    printf '\n%d check(s) failed; outputs kept in %s\n' "$failures" "$output_dir" >&2
    exit 1
fi

printf '\nAll run pages are self-contained.\n'
printf 'Standalone reports: %s/reports/\n' "$output_dir"
