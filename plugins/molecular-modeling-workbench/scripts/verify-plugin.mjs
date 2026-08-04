#!/usr/bin/env node
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const expected = [
	"molecular-modeling-environment",
	"molecular-geometry-common",
	"docking-project-manager",
	"docking-simulation-run",
	"docking-complex-analysis",
	"docking-to-md-handoff",
	"docking-visualization",
	"ligand-parameterization",
	"md-project-manager",
	"md-simulation-run",
	"md-trajectory-analysis",
	"md-simulation-plotting",
];

export function verifyPlugin() {
	const manifestPath = resolve(root, ".codex-plugin/plugin.json");
	if (!existsSync(manifestPath))
		throw new Error("Missing .codex-plugin/plugin.json");
	const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
	const meta = JSON.parse(
		readFileSync(resolve(root, "plugin-meta.json"), "utf8"),
	);
	if (manifest.name !== meta.name)
		throw new Error("Plugin manifest name must match plugin-meta.json.");
	if (manifest.skills !== "./skills/")
		throw new Error("Plugin must expose ./skills/.");
	const claudeManifestPath = resolve(root, ".claude-plugin/plugin.json");
	if (!existsSync(claudeManifestPath))
		throw new Error("Missing .claude-plugin/plugin.json; run npm run sync.");
	const claude = JSON.parse(readFileSync(claudeManifestPath, "utf8"));
	if (claude.name !== manifest.name)
		throw new Error(
			"Claude plugin manifest name must match the codex manifest.",
		);
	if (claude.version !== manifest.version)
		throw new Error(
			"Claude plugin manifest version must match the codex manifest.",
		);
	if (!existsSync(resolve(root, "../../.claude-plugin/marketplace.json")))
		throw new Error(
			"Missing repo-root .claude-plugin/marketplace.json; run npm run sync.",
		);
	if (!existsSync(resolve(root, "bundle-manifest.json")))
		throw new Error("Missing bundle-manifest.json; run npm run sync.");
	const runtimeContractPath = resolve(root, "runtime-contract.json");
	if (!existsSync(runtimeContractPath))
		throw new Error("Missing runtime-contract.json.");
	const runtimeContract = JSON.parse(readFileSync(runtimeContractPath, "utf8"));
	if (
		runtimeContract.artifact_type !== "molecular_modeling_runtime_contract" ||
		runtimeContract.schema_version !== "1.0"
	)
		throw new Error("Runtime contract schema is invalid.");
	if (
		runtimeContract.onboarding?.windows_host !== "Windows 11" ||
		runtimeContract.onboarding?.wsl_distribution !== "Ubuntu-22.04" ||
		runtimeContract.onboarding?.scientific_execution !== "wsl-native-only"
	)
		throw new Error("Windows-to-WSL onboarding contract is invalid.");
	for (const path of [
		"scripts/Start-AI4S-Workbench.ps1",
		"scripts/setup-wsl-workbench.sh",
	])
		if (!existsSync(resolve(root, path)))
			throw new Error(`Missing onboarding entrypoint: ${path}`);
	for (const path of ["pyproject.toml", "uv.lock"])
		if (!existsSync(resolve(root, path)))
			throw new Error(`Missing locked Python runtime file: ${path}`);
	for (const skill of expected)
		if (!existsSync(resolve(root, "skills", skill, "SKILL.md")))
			throw new Error(`Bundled skill is missing: ${skill}`);
	return `Plugin manifests, onboarding entrypoints, and ${expected.length} bundled skills verified.`;
}

const isMain =
	process.argv[1] &&
	resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) process.stdout.write(`${verifyPlugin()}\n`);
