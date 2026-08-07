#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
runtime_dir="$script_dir/../runtime"
fulltext_runtime_dir="$script_dir/../fulltext-runtime"
required_major=20
required_minor=19

if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
	echo "Node.js and npm are required. Install Node.js 20.19 or newer." >&2
	exit 1
fi

version="$(node -p 'process.versions.node')"
IFS='.' read -r major minor _ <<<"$version"
if ((major < required_major || (major == required_major && minor < required_minor))); then
	echo "Node.js $version is unsupported; require Node.js 20.19 or newer." >&2
	exit 1
fi

cd "$runtime_dir"
npm ci
npm run build
node ../scripts/verify-runtime.mjs

if [[ -d "$fulltext_runtime_dir" ]]; then
	if (
		cd "$fulltext_runtime_dir"
		npm ci
		npm run build
		node ../scripts/verify-fulltext-runtime.mjs
	); then
		echo "Optional literature Fulltext MCP is ready (OA-only)."
	else
		echo "Warning: the optional literature Fulltext MCP was not installed. Zotero MCP and literature skills remain available." >&2
	fi
fi

echo
echo "Optional API onboarding is available; basic literature features work without keys."
echo "On the first workbench conversation, the Agent will explain Zotero Web API, PubMed, and EasyScholar setup."
echo "Local masked wizard: node \"$script_dir/onboard.mjs\" setup --output onboarding-result.json"
