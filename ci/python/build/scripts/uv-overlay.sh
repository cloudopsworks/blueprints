#!/usr/bin/env bash
##
# (c) 2021-2026
#     Cloud Ops Works LLC - https://cloudops.works/
#     Find us on:
#       GitHub: https://github.com/cloudopsworks
#       WebSite: https://cloudops.works
#     Distributed Under Apache v2.0 License
#
# uv-overlay.sh <venv-python> <out-file> <module>=<spec> [...]
# Writes a requirements file for `uv run --with-requirements` to <out-file>.
# <out-file> is left EMPTY when the venv already provides every requested module (app wins).
# Tiers, each constrained to the exact versions installed in the venv:
#   1. blueprint pins   2. same-major range (pkg>=M,<M+1)   3. unconstrained pins + ::warning:: (may shadow)
# Venv probes run with -I so cwd dirs (e.g. coverage/ html reports, *.egg-info) are not mistaken for packages.
# Callers must set UV_PYTHON_DOWNLOADS=never in the step env.
set -eo pipefail
VENV_PY="$1"; OUT="$2"; shift 2
: > "$OUT"
PINS=(); FLOORS=()
for pair in "$@"; do
  mod="${pair%%=*}"; spec="${pair#*=}"
  if "$VENV_PY" -I -c 'import importlib.util,sys;sys.exit(0 if importlib.util.find_spec(sys.argv[1]) else 1)' "$mod"; then
    echo "::notice::${mod}: using the version installed by the application"
    continue
  fi
  PINS+=("$spec")
  if [[ "$spec" == *"=="* ]]; then
    ver="${spec#*==}"; maj="${ver%%.*}"; FLOORS+=("${spec%%==*}>=${maj},<$((maj + 1))")
  else
    FLOORS+=("$spec")
  fi
done
if [ ${#PINS[@]} -eq 0 ]; then
  echo "Tool overlay: none (application provides all requested tools)"
  exit 0
fi
C="$(mktemp)"; ERR="$(mktemp)"
trap 'rm -f "$C" "$ERR"' EXIT
"$VENV_PY" -I - > "$C" <<'PY'
import importlib.metadata as m, re
seen = set()
for d in m.distributions():
    n = re.sub(r"[-_.]+", "-", (d.metadata.get("Name") or "").strip()).lower()
    if n and n not in seen:
        seen.add(n); print(f"{n}=={d.version}")
PY
compile() { printf '%s\n' "$@" | uv pip compile -q --no-header --no-annotate -p "$VENV_PY" -c "$C" - -o "$OUT" 2>"$ERR"; }
if compile "${PINS[@]}"; then
  echo "Tool overlay (pinned, app versions kept): ${PINS[*]}"
elif compile "${FLOORS[@]}"; then
  echo "::warning::Could not resolve pinned tool overlay against installed app packages; using same-major compatible versions (${FLOORS[*]})"
  tail -n 4 "$ERR" || true
else
  echo "::warning::Could not resolve constrained tool overlay (see error below); using unconstrained pins, which may shadow app packages"
  cat "$ERR"
  printf '%s\n' "${PINS[@]}" > "$OUT"
fi
echo "--- Resolved tool overlay ($OUT) ---"
cat "$OUT"
