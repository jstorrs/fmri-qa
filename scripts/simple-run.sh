#!/usr/bin/env bash
# Usage: ./scripts/simple-run.sh [DICOM_DIRECTORY [OUTPUT_DIRECTORY]]
# Requires: uv sync --all-packages
#
# The whole pipeline as one step: a directory of DICOM in, and for each series
# found a directory named after it holding four files:
#
#   OUTPUT_DIRECTORY/<series>/<series>.nii.gz   the converted scan
#   OUTPUT_DIRECTORY/<series>/<series>.json     its acquisition sidecar
#   OUTPUT_DIRECTORY/<series>/<series>.qa.nc    the QA results
#   OUTPUT_DIRECTORY/<series>/<series>.html     the report; double-click to open
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
source_dir=${1:-/scratch/usbstick/coils/fbirn_64ch_run2}

if (( $# > 2 )) || [[ ! -d "$source_dir" ]]; then
    printf 'Usage: %s [DICOM_DIRECTORY [OUTPUT_DIRECTORY]]\n' "$0" >&2
    printf 'DICOM_DIRECTORY must be an existing directory.\n' >&2
    exit 1
fi

if (( $# == 2 )); then
    output_dir=$2
    mkdir -p "$output_dir"
else
    mkdir -p "$repo_root/build"
    output_dir=$(mktemp -d "$repo_root/build/simple-run.XXXXXX")
    # mktemp makes the directory private; results are meant to be shared.
    chmod 755 "$output_dir"
fi
printf 'Writing results to %s\n' "$output_dir"

run() {
    uv run --project "$repo_root" --all-packages "$@"
}

# A series is only named once it has been converted, so the import lands in a
# hidden staging directory and each series then moves to its own directory.
staging=$(mktemp -d "$output_dir/.simple-run.XXXXXX")
trap 'rm -rf -- "$staging"' EXIT

run fmri-qa-import "$source_dir" --out "$staging"

shopt -s nullglob
scans=("$staging/"*.nii.gz)
if (( ${#scans[@]} == 0 )); then
    printf 'No scans were found in %s\n' "$source_dir" >&2
    exit 1
fi

reports=()
for scan in "${scans[@]}"; do
    name=$(basename -- "$scan" .nii.gz)
    series_dir=$output_dir/$name
    if [[ -e "$series_dir" ]]; then
        printf 'Refusing to replace existing results: %s\n' "$series_dir" >&2
        exit 1
    fi
    mkdir "$staging/$name"
    mv -- "$staging/$name".* "$staging/$name/"
    run fmri-qa "$staging/$name/$name.nii.gz" --artifact "$staging/$name"
    run fmri-qa-report "$staging/$name/$name.qa.nc" --html "$staging/$name/$name.html"
    # Only a finished series appears in the output directory.
    mv -- "$staging/$name" "$series_dir"
    reports+=("$series_dir/$name.html")
done

printf '\nReports:\n'
printf '  %s\n' "${reports[@]}"
