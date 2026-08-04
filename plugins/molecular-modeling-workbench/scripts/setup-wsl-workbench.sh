#!/usr/bin/env bash
set -euo pipefail
umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PLUGIN_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
AGENT=""
WORKSPACE="$HOME/AI4S-Workbench-Projects"
ENVIRONMENT_DIR=""
OUTPUT_DIR=""
SUMMARY=""
CURRENT_STEP="initial validation"

usage() {
	cat <<'EOF'
Usage: bash scripts/setup-wsl-workbench.sh --agent <codex|claude> [options]

Options:
  --agent <codex|claude>   Select the WSL-native Agent handoff (required).
  --workspace <path>       Scientific workspace under the WSL Linux home.
                           Default: $HOME/AI4S-Workbench-Projects
  --environment-dir <path> New environment artifacts directory.
                           Default: <workspace>/environment
  --output-dir <path>      New directory for this run's summary and handoff.
                           Default: <workspace>/onboarding-runs/<timestamp-pid>
  -h, --help               Show this help.

Output and environment targets must not already exist, including symbolic links.
This initializer diagnoses and writes checklists. It does not use sudo, install
Docker/GPU drivers/ChimeraX, handle credentials, or authenticate an Agent.
EOF
}

write_summary() {
	local status="$1"
	local detail="$2"
	[[ -n "$SUMMARY" && -d "$(dirname -- "$SUMMARY")" ]] || return 0
	local temporary="$SUMMARY.tmp.$$"
	cat >"$temporary" <<EOF
# WSL workbench setup

- Status: **$status**
- Step: $CURRENT_STEP
- Detail: $detail
- Workspace: \`$WORKSPACE\`
- Locked project: \`$PLUGIN_ROOT/pyproject.toml\`
- Environment directory: \`${ENVIRONMENT_DIR:-not selected}\`
- Run output: \`${OUTPUT_DIR:-not selected}\`

No Agent login, privileged host change, Docker installation, or scientific calculation was performed by this initializer.
EOF
	mv -f -- "$temporary" "$SUMMARY"
}

fail() {
	local message="$1"
	local status="${2:-2}"
	write_summary "failed" "$message"
	printf 'Error: %s\n' "$message" >&2
	exit "$status"
}

while (($#)); do
	case "$1" in
	--agent)
		(($# >= 2)) || fail "--agent requires codex or claude."
		AGENT="$2"
		shift 2
		;;
	--workspace)
		(($# >= 2)) || fail "--workspace requires a path."
		WORKSPACE="$2"
		shift 2
		;;
	--environment-dir)
		(($# >= 2)) || fail "--environment-dir requires a path."
		ENVIRONMENT_DIR="$2"
		shift 2
		;;
	--output-dir)
		(($# >= 2)) || fail "--output-dir requires a path."
		OUTPUT_DIR="$2"
		shift 2
		;;
	-h | --help)
		usage
		exit 0
		;;
	*)
		fail "Unknown option: $1"
		;;
	esac
done

case "$AGENT" in
codex | claude) ;;
*) fail "Choose exactly one WSL-native Agent with --agent codex or --agent claude." ;;
esac

kernel_release="$(uname -r 2>/dev/null || true)"
if [[ "${kernel_release,,}" != *microsoft-standard-wsl2* ]]; then
	fail "This initializer runs only inside WSL2. From Windows, open Ubuntu-22.04 and try again."
fi

# shellcheck disable=SC1091
source /etc/os-release
if [[ "${ID:-}" != "ubuntu" || "${VERSION_ID:-}" != "22.04" ]]; then
	fail "v0.2.0 supports Ubuntu 22.04 on WSL2 only; detected ${PRETTY_NAME:-unknown distribution}."
fi
if [[ "${WSL_DISTRO_NAME:-}" != "Ubuntu-22.04" ]]; then
	fail "Open the explicitly supported Ubuntu-22.04 WSL distribution (detected: ${WSL_DISTRO_NAME:-unset})."
fi

case "$PLUGIN_ROOT" in
/mnt/*) fail "The plugin checkout is under /mnt/*. Re-clone it under the WSL Linux home filesystem." ;;
esac

if [[ "$WORKSPACE" != /* ]]; then
	WORKSPACE="$PWD/$WORKSPACE"
fi
[[ ! -L "$WORKSPACE" ]] || fail "The workspace itself cannot be a symbolic link: $WORKSPACE"
WORKSPACE="$(realpath -m -- "$WORKSPACE")"
case "$WORKSPACE" in
/mnt/*) fail "Scientific projects cannot use /mnt/*. Choose a workspace under $HOME." ;;
"$HOME" | "$HOME"/*) ;;
*) fail "Scientific projects must remain under the current WSL Linux home: $HOME" ;;
esac

mkdir -p -- "$WORKSPACE"
workspace_fs="$(stat -f -c %T -- "$WORKSPACE")"
case "$workspace_fs" in
ext2/ext3 | ext4) ;;
*) fail "Scientific projects require the WSL ext4 filesystem; detected $workspace_fs at $WORKSPACE." ;;
esac

if [[ -z "$OUTPUT_DIR" ]]; then
	run_stamp="$(date -u +%Y%m%dT%H%M%SZ)-$$"
	OUTPUT_DIR="$WORKSPACE/onboarding-runs/$run_stamp"
elif [[ "$OUTPUT_DIR" != /* ]]; then
	OUTPUT_DIR="$PWD/$OUTPUT_DIR"
fi
[[ ! -e "$OUTPUT_DIR" && ! -L "$OUTPUT_DIR" ]] || fail "Refusing to overwrite existing onboarding output: $OUTPUT_DIR. Choose a new --output-dir."
OUTPUT_DIR="$(realpath -m -- "$OUTPUT_DIR")"
case "$OUTPUT_DIR" in
"$WORKSPACE"/*) ;;
*) fail "--output-dir must be a new directory inside the selected scientific workspace." ;;
esac
[[ ! -e "$OUTPUT_DIR" && ! -L "$OUTPUT_DIR" ]] || fail "Refusing to overwrite existing onboarding output: $OUTPUT_DIR. Choose a new --output-dir."
mkdir -p -- "$(dirname -- "$OUTPUT_DIR")"
mkdir -- "$OUTPUT_DIR"
SUMMARY="$OUTPUT_DIR/setup-summary.md"
HANDOFF="$OUTPUT_DIR/agent-handoff.md"
CURRENT_STEP="environment target validation"
write_summary "in progress" "Host and workspace checks passed."

on_unexpected_error() {
	local status="$1"
	local line="$2"
	trap - ERR
	write_summary "failed" "Unexpected initializer error at line $line (exit $status). Review the terminal diagnostics and use new output targets when retrying."
	exit "$status"
}
trap 'on_unexpected_error "$?" "$LINENO"' ERR

if [[ -z "$ENVIRONMENT_DIR" ]]; then
	ENVIRONMENT_DIR="$WORKSPACE/environment"
elif [[ "$ENVIRONMENT_DIR" != /* ]]; then
	ENVIRONMENT_DIR="$PWD/$ENVIRONMENT_DIR"
fi
[[ ! -e "$ENVIRONMENT_DIR" && ! -L "$ENVIRONMENT_DIR" ]] || fail "Refusing to overwrite existing environment diagnostics: $ENVIRONMENT_DIR. Choose a new --environment-dir for a retry, or review the existing artifacts."
ENVIRONMENT_DIR="$(realpath -m -- "$ENVIRONMENT_DIR")"
case "$ENVIRONMENT_DIR" in
"$WORKSPACE"/*) ;;
*) fail "--environment-dir must be a new directory inside the selected scientific workspace." ;;
esac
[[ ! -e "$ENVIRONMENT_DIR" && ! -L "$ENVIRONMENT_DIR" ]] || fail "Refusing to overwrite existing environment diagnostics: $ENVIRONMENT_DIR. Choose a new --environment-dir."

CURRENT_STEP="Agent handoff"
if [[ "$AGENT" == "codex" ]]; then
	agent_name="Codex CLI"
	agent_command="codex"
	agent_install="npm install -g @openai/codex"
	agent_docs="https://help.openai.com/en/articles/11096431"
else
	agent_name="Claude Code"
	agent_command="claude"
	agent_install="Follow the currently published installation step on the official Claude Code page after reviewing it."
	agent_docs="https://docs.anthropic.com/en/docs/claude-code/getting-started"
fi

agent_status="not detected"
if command -v "$agent_command" >/dev/null 2>&1; then
	agent_status="detected at $(command -v "$agent_command")"
fi
node_status="not detected (recorded only; this initializer does not block on Node.js)"
command -v node >/dev/null 2>&1 && node_status="$(node --version 2>/dev/null || command -v node)"
npm_status="not detected"
command -v npm >/dev/null 2>&1 && npm_status="detected at $(command -v npm)"
docker_status="not detected in WSL"
command -v docker >/dev/null 2>&1 && docker_status="detected at $(command -v docker); environment onboarding will verify access"
gpu_status="/dev/dxg not visible"
[[ -e /dev/dxg ]] && gpu_status="/dev/dxg visible; environment onboarding will verify capability"

cat >"$HANDOFF" <<EOF
# $agent_name handoff

Status: **$agent_status**

Official instructions: <$agent_docs>

Installation handoff (review and run yourself):

\`\`\`text
$agent_install
\`\`\`

Node.js: $node_status
npm: $npm_status

After installation, start \`$agent_command\` yourself and complete the official browser/subscription authentication flow. The workbench never reads, stores, or submits credentials for you.

Run the Agent from this WSL workspace:

\`\`\`bash
cd "$WORKSPACE"
$agent_command
\`\`\`

Do not use a Windows desktop Agent as the docking or MD command executor.
EOF

CURRENT_STEP="locked runtime check"
if ! command -v uv >/dev/null 2>&1; then
	fail "uv is required for the locked workbench runtime. Follow the reviewed official instructions at https://docs.astral.sh/uv/getting-started/installation/ and rerun with new output and environment targets."
fi

ENVIRONMENT_SCRIPT="$PLUGIN_ROOT/skills/molecular-modeling-environment/scripts/molecular_modeling_environment.py"
[[ -f "$ENVIRONMENT_SCRIPT" ]] || fail "Bundled environment workflow is missing: $ENVIRONMENT_SCRIPT"

CURRENT_STEP="environment onboarding"
if uv run --project "$PLUGIN_ROOT" --locked "$ENVIRONMENT_SCRIPT" onboard --profile wsl2-gpu --output-dir "$ENVIRONMENT_DIR"; then
	:
else
	status=$?
	fail "Environment onboarding exited with status $status. Review terminal diagnostics and retry with new --output-dir and --environment-dir targets." "$status"
fi

CURRENT_STEP="complete"
cat >"$SUMMARY.tmp.$$" <<EOF
# WSL workbench setup

- Status: **complete**
- Host: Ubuntu 22.04 on WSL2
- Workspace: \`$WORKSPACE\`
- Run output: \`$OUTPUT_DIR\`
- Locked project: \`$PLUGIN_ROOT/pyproject.toml\`
- Locked runtime: \`$(command -v uv)\`
- Node.js: $node_status
- npm: $npm_status
- Docker: $docker_status
- GPU bridge: $gpu_status
- Agent: $agent_name ($agent_status)
- Agent handoff: \`$HANDOFF\`
- Environment checklist: \`$ENVIRONMENT_DIR/onboarding_checklist.md\`
- Environment evidence: \`$ENVIRONMENT_DIR/onboarding_checklist.json\`

The checklist is diagnostic. Review its installation handoffs before generating an install plan. Docking and MD remain blocked until a later \`verify\` command writes a current \`environment_receipt.json\` with \`ready: true\`.
EOF
mv -f -- "$SUMMARY.tmp.$$" "$SUMMARY"
trap - ERR

printf 'WSL onboarding checklist written to: %s\n' "$ENVIRONMENT_DIR/onboarding_checklist.md"
printf 'Agent handoff written to: %s\n' "$HANDOFF"
printf 'Setup summary written to: %s\n' "$SUMMARY"
printf 'No Agent login, privileged host change, Docker installation, or scientific calculation was performed.\n'
