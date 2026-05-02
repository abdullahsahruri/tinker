# socc26-2 project environment.
#
# Source this from a Bash shell to activate the project toolchain:
#   $ source scripts/env.sh
#
# What it does:
#   * Activates the project venv (LibreLane, volare, ...).
#   * Exports PDK_ROOT/PDK/STD_CELL_LIBRARY pointing at the project-local sky130A.
#   * Scrubs /mnt/c/... (Windows-mount) and stale OSS-CAD-Suite entries from PATH
#     so Linux-side EDA tools win deterministically inside this shell.
#
# It does NOT modify ~/.bashrc or any system-wide config. The scrub is local to
# the sourcing shell only — open a new shell and the original PATH is intact.

# Resolve the project root regardless of where the user sources from.
# Works under bash; under zsh use ${(%):-%x}, but the project is bash-first.
if [ -n "${BASH_SOURCE[0]:-}" ]; then
    _SOCC26_ENV_SH="${BASH_SOURCE[0]}"
elif [ -n "${ZSH_VERSION:-}" ]; then
    _SOCC26_ENV_SH="${(%):-%x}"
else
    _SOCC26_ENV_SH="$0"
fi
SOCC26_ROOT="$(cd "$(dirname "${_SOCC26_ENV_SH}")/.." && pwd)"
unset _SOCC26_ENV_SH
export SOCC26_ROOT

# --- venv ---------------------------------------------------------------
if [ -f "${SOCC26_ROOT}/.venv/bin/activate" ]; then
    # shellcheck source=/dev/null
    . "${SOCC26_ROOT}/.venv/bin/activate"
else
    echo "socc26-2: WARNING — .venv not found at ${SOCC26_ROOT}/.venv" >&2
fi

# --- PDK ----------------------------------------------------------------
export PDK_ROOT="${SOCC26_ROOT}/pdk"
export PDK="sky130A"
export STD_CELL_LIBRARY="sky130_fd_sc_hd"

# --- LibreLane Docker image pin ----------------------------------------
# Override only if you need a non-matching image (we pin to the package version).
export LIBRELANE_IMAGE_OVERRIDE="${LIBRELANE_IMAGE_OVERRIDE:-ghcr.io/librelane/librelane:3.0.3}"

# --- PATH scrub --------------------------------------------------------
# Remove /mnt/c/... and stale OSS-CAD-Suite entries so apt-installed Linux
# binaries (e.g. /usr/bin/verilator) win. This is reversible: it edits PATH
# only in the current shell; closing the shell restores the original.
_socc26_scrub_path() {
    local input="${1:-${PATH}}"
    local out="" entry
    local IFS=":"
    for entry in $input; do
        case "$entry" in
            /mnt/c/* )                              continue ;;  # Windows mount
            /mnt/c/tools/oss-cad-suite/* )          continue ;;  # explicit, just in case
            /Docker/host/bin )                      continue ;;  # Docker Desktop pseudo-path
        esac
        if [ -n "$out" ]; then
            out="${out}:${entry}"
        else
            out="$entry"
        fi
    done
    printf '%s' "$out"
}
PATH="$(_socc26_scrub_path "$PATH")"
export PATH
unset -f _socc26_scrub_path

# --- Friendly banner ---------------------------------------------------
cat <<EOF
[socc26-2] env activated
  SOCC26_ROOT          = ${SOCC26_ROOT}
  PDK_ROOT             = ${PDK_ROOT}
  PDK / STD_CELL       = ${PDK} / ${STD_CELL_LIBRARY}
  LibreLane image      = ${LIBRELANE_IMAGE_OVERRIDE}
  venv                 = $(which python 2>/dev/null || echo '<not on PATH>')
EOF
