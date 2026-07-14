#!/usr/bin/env bash
# Phase S1 test runner.
#
# Runs the suite in memory-isolated batches (a fresh Python process each) so it
# passes reliably on constrained CI boxes. The performance module intentionally
# loads a 100k-row dataset and renders it repeatedly to assert timing budgets;
# running everything in a single process stacks that peak on top of the render
# suites and can exhaust a small (<=4 GB) container. Batching avoids that without
# weakening any test.
#
# Usage:  bash scripts/run_tests.sh
set -u
export MPLBACKEND=Agg
export FAP_TEST=1
PY="${PY:-python}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

fail=0
run() {
  echo ""
  echo "================ $1 ================"
  # shellcheck disable=SC2086
  $PY -m pytest $2 -q --no-header -p no:cacheprovider || fail=1
}

# Batch 1 - fast core (auth, cache, pipeline, registry, themes, persistence, providers, data)
run "core + data + providers" \
  "tests/test_auth_workflow.py tests/test_cache.py tests/test_pipeline.py \
   tests/test_plugin_registry.py tests/test_themes.py tests/test_persistence.py \
   tests/test_data_engine.py tests/test_providers.py tests/test_export_and_themes.py \
   tests/test_stabilization_s1.py"

# Batch 2 - heavy render suites
run "visual framework + match analysis" \
  "tests/test_visual_framework.py tests/test_match_analysis_library.py"

# Batch 3 - performance (100k-row dataset, isolated so its peak doesn't stack)
run "performance + providers compat" \
  "tests/test_performance_and_providers.py"

echo ""
echo "================ open-play scripts ================"
$PY tests/test_phase7.py       || fail=1
$PY tests/deep_validate.py     || fail=1

echo ""
if [ "$fail" -eq 0 ]; then
  echo "ALL BATCHES PASSED"
else
  echo "SOME BATCHES FAILED"
fi
exit $fail
