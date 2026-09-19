import assert from "node:assert/strict";
import {
	existsSync,
	mkdirSync,
	mkdtempSync,
	readFileSync,
	rmSync,
	writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import test from "node:test";
import { checkPluginAssembly, treeHash } from "../scripts/assemble-plugin.mjs";

const root = resolve(import.meta.dirname, "..");
const repoRoot = resolve(root, "../..");

function readText(path) {
	try {
		return readFileSync(path, "utf8");
	} catch (error) {
		assert.fail(`Unable to read ${path}: ${error.message}`);
	}
}

function readJson(path) {
	try {
		return JSON.parse(readText(path));
	} catch (error) {
		assert.fail(`Unable to parse JSON at ${path}: ${error.message}`);
	}
}

test("package.json is the release version source and matches plugin metadata", () => {
	const pkg = readJson(resolve(root, "package.json"));
	const meta = readJson(resolve(root, "plugin-meta.json"));
	for (const key of [
		"name",
		"version",
		"description",
		"author",
		"license",
		"codex",
		"marketplace",
	]) {
		assert.ok(meta[key], `plugin-meta.json missing ${key}`);
	}
	assert.match(pkg.version, /^\d+\.\d+\.\d+$/);
	assert.equal(pkg.version, meta.version);
	assert.equal(pkg.version, "0.3.0");
});

test("codex and claude manifests are generated and synchronized", () => {
	assert.match(checkPluginAssembly(), /match all source skills/);
	const codex = readJson(resolve(root, ".codex-plugin/plugin.json"));
	const claude = readJson(resolve(root, ".claude-plugin/plugin.json"));
	assert.equal(claude.name, codex.name);
	assert.equal(claude.version, codex.version);
	assert.equal(codex.skills, "./skills/");
	assert.ok(codex.interface.displayName);
	assert.equal(claude.interface, undefined);
});

test("tree hashing excludes local caches from reproducible bundle manifests", () => {
	const root = mkdtempSync(resolve(tmpdir(), "ai4s-bundle-hash-"));
	try {
		writeFileSync(resolve(root, "tracked.txt"), "stable content\n");
		const baseline = treeHash(root);
		mkdirSync(resolve(root, ".ruff_cache"));
		writeFileSync(resolve(root, ".ruff_cache", "state"), "machine-local state\n");
		mkdirSync(resolve(root, ".venv"));
		writeFileSync(resolve(root, ".venv", "marker"), "environment state\n");
		assert.equal(treeHash(root), baseline);
	} finally {
		rmSync(root, { recursive: true, force: true });
	}
});

test("repository root exposes a claude marketplace listing this plugin", () => {
	const marketplace = readJson(
		resolve(repoRoot, ".claude-plugin/marketplace.json"),
	);
	const meta = readJson(resolve(root, "plugin-meta.json"));
	assert.equal(typeof marketplace.name, "string");
	const entry = marketplace.plugins.find((p) => p.name === meta.name);
	assert.ok(entry, "plugin missing from marketplace");
	assert.equal(entry.source, `./plugins/${meta.name}`);
	assert.ok(
		existsSync(resolve(repoRoot, entry.source, ".claude-plugin/plugin.json")),
	);
});

test("runtime contract and Python lock are present", () => {
	const contract = readJson(resolve(root, "runtime-contract.json"));
	assert.equal(contract.artifact_type, "molecular_modeling_runtime_contract");
	assert.equal(contract.python.lockfile, "uv.lock");
	assert.equal(contract.onboarding.windows_wsl.windows_host, "Windows 11");
	assert.equal(contract.onboarding.windows_wsl.wsl_distribution, "Ubuntu-22.04");
	assert.equal(
		contract.onboarding.scientific_execution,
		"native-linux-or-wsl-native",
	);
	assert.ok(contract.onboarding.supported_gpu_profiles.includes("linux-gpu"));
	assert.ok(contract.onboarding.supported_gpu_profiles.includes("wsl2-gpu"));
	assert.equal(existsSync(resolve(root, "pyproject.toml")), true);
	assert.equal(existsSync(resolve(root, "uv.lock")), true);
});

test("repository CI runs the locked CPU-only suite", () => {
	const workflow = readText(resolve(repoRoot, ".github/workflows/ci.yml"));
	const meta = readJson(resolve(root, "plugin-meta.json"));
	assert.match(workflow, new RegExp(`working-directory: plugins/${meta.name}`));
	assert.match(workflow, /npm run check/);
	assert.match(workflow, /npm test/);
	assert.match(workflow, /runs-on: ubuntu-22\.04/);
	assert.match(workflow, /workflow_dispatch/);
	assert.match(workflow, /contents: read/);
});

test("test runner is platform-neutral and preserves the locked Python contract", () => {
	const pkg = readJson(resolve(root, "package.json"));
	assert.equal(pkg.scripts.test, "node scripts/run-tests.mjs");
	assert.equal(
		pkg.scripts["test:all"],
		"node scripts/run-tests.mjs --include-deferred --include-web",
	);
	assert.equal(pkg.scripts["test:web"], "node scripts/run-tests.mjs --web-only");
	const runner = readText(resolve(root, "scripts/run-tests.mjs"));
	assert.match(runner, /deferredPythonSuites/);
	assert.match(runner, /--include-deferred/);
	assert.match(runner, /--project.*web/);
	assert.match(runner, /--locked/);
	assert.match(runner, /spawnSync/);
	assert.doesNotMatch(runner, /bash -lc|PYTHONPYCACHEPREFIX=.*&&/);
});
