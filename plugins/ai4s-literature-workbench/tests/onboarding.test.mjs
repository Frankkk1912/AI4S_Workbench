import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, win32 } from "node:path";
import { test } from "node:test";

import {
	onboardingPaths,
	redactedStatus,
	verifyEasyScholarKey,
	verifyPubmedKey,
	verifyZoteroKey,
} from "../scripts/onboard.mjs";

test("Windows onboarding paths use LOCALAPPDATA", () => {
	const paths = onboardingPaths(
		{ LOCALAPPDATA: "C:\\Users\\Frank\\AppData\\Local" },
		"win32",
		"C:\\Users\\Frank",
	);
	assert.equal(
		paths.zoteroEnv,
		win32.join(
			"C:\\Users\\Frank\\AppData\\Local",
			"ai4s-literature-workbench",
			"zotero.env",
		),
	);
	assert.equal(
		paths.academicConfig,
		win32.join(
			"C:\\Users\\Frank\\AppData\\Local",
			"frank-ai4s",
			"academic-research.json",
		),
	);
});

test("redacted status detects keys without exposing values or hidden providers", () => {
	const root = mkdtempSync(join(tmpdir(), "ai4s-onboarding-"));
	const paths = {
		zoteroEnv: join(root, "zotero.env"),
		academicConfig: join(root, "academic-research.json"),
		state: join(root, "onboarding.json"),
	};
	const secrets = {
		zotero: "zotero-secret-example",
		pubmed: "pubmed-secret-example",
		easyscholar: "easyscholar-secret-example",
		hidden: "hidden-provider-secret",
	};
	writeFileSync(paths.zoteroEnv, `ZOTERO_API_KEY=${secrets.zotero}\n`, "utf8");
	writeFileSync(
		paths.academicConfig,
		JSON.stringify({
			pubmed_api_key: secrets.pubmed,
			easyscholar_secret_key: secrets.easyscholar,
			s2_api_key: secrets.hidden,
		}),
		"utf8",
	);

	const status = redactedStatus(paths, {});
	const serialized = JSON.stringify(status);
	assert.equal(status.first_run, true);
	assert.equal(status.baseline_available, true);
	assert.deepEqual(Object.keys(status.providers), [
		"zotero",
		"pubmed",
		"easyscholar",
	]);
	assert.equal(status.zotero_desktop_xpi.status, "manual_install_required");
	assert.match(
		status.zotero_desktop_xpi.artifact,
		/^source\/literature-metrics\/dist\/literature-metrics-.*\.xpi$/,
	);
	assert.match(status.zotero_desktop_xpi.install, /Install Add-on From File/i);
	for (const secret of Object.values(secrets))
		assert.equal(serialized.includes(secret), false);
	assert.equal(serialized.toLowerCase().includes("semantic"), false);
});

test("provider validators return only redacted capabilities", async () => {
	const requests = [];
	const mockFetch = async (url, options = {}) => {
		requests.push({ url: String(url), options });
		if (String(url).includes("zotero")) {
			return new Response(
				JSON.stringify({
					userID: 42,
					username: "researcher",
					access: {
						user: { library: true, write: false, files: true },
						groups: { 7: { library: true } },
					},
				}),
				{ status: 200 },
			);
		}
		if (String(url).includes("einfo")) {
			return new Response(
				JSON.stringify({ einforesult: { dblist: ["pubmed"] } }),
				{ status: 200 },
			);
		}
		return new Response(
			JSON.stringify({ code: 200, data: { officialRank: {} } }),
			{ status: 200 },
		);
	};

	const zotero = await verifyZoteroKey("z-secret", mockFetch);
	const pubmed = await verifyPubmedKey("p-secret", mockFetch);
	const easyscholar = await verifyEasyScholarKey("e-secret", mockFetch);
	assert.deepEqual(zotero, {
		library: true,
		write: false,
		files: true,
		notes: false,
		groups: 1,
	});
	assert.deepEqual(pubmed, { valid: true });
	assert.deepEqual(easyscholar, { valid: true });
	const results = JSON.stringify({ zotero, pubmed, easyscholar });
	assert.equal(results.includes("z-secret"), false);
	assert.equal(results.includes("p-secret"), false);
	assert.equal(results.includes("e-secret"), false);
	assert.equal(requests.length, 3);
});

test("status command writes a file and can mark the guide as offered", async () => {
	const root = mkdtempSync(join(tmpdir(), "ai4s-onboarding-command-"));
	const output = join(root, "status.json");
	const old = {
		state: process.env.AI4S_ONBOARDING_STATE_FILE,
		academic: process.env.AI4S_ACADEMIC_CONFIG_FILE,
		zotero: process.env.LITERATURE_ZOTERO_MCP_ENV_FILE,
	};
	process.env.AI4S_ONBOARDING_STATE_FILE = join(root, "state.json");
	process.env.AI4S_ACADEMIC_CONFIG_FILE = join(root, "academic.json");
	process.env.LITERATURE_ZOTERO_MCP_ENV_FILE = join(root, "zotero.env");
	const { main } = await import("../scripts/onboard.mjs");
	try {
		await main(["status", "--mark-offered", "--output", output]);
		const report = JSON.parse(readFileSync(output, "utf8"));
		assert.equal(report.first_run, false);
		assert.equal(report.baseline_available, true);
		assert.equal(report.zotero_desktop_xpi.status, "manual_install_required");
	} finally {
		if (old.state === undefined) delete process.env.AI4S_ONBOARDING_STATE_FILE;
		else process.env.AI4S_ONBOARDING_STATE_FILE = old.state;
		if (old.academic === undefined)
			delete process.env.AI4S_ACADEMIC_CONFIG_FILE;
		else process.env.AI4S_ACADEMIC_CONFIG_FILE = old.academic;
		if (old.zotero === undefined)
			delete process.env.LITERATURE_ZOTERO_MCP_ENV_FILE;
		else process.env.LITERATURE_ZOTERO_MCP_ENV_FILE = old.zotero;
	}
});

test("plugin default prompt advertises first-run onboarding", () => {
	const manifest = JSON.parse(
		readFileSync(
			new URL("../.codex-plugin/plugin.json", import.meta.url),
			"utf8",
		),
	);
	assert.match(
		manifest.interface.defaultPrompt[0],
		/first-run API onboarding/i,
	);
	assert.match(manifest.interface.defaultPrompt[0], /Zotero Web API/);
	assert.match(manifest.interface.defaultPrompt[0], /PubMed/);
	assert.match(manifest.interface.defaultPrompt[0], /EasyScholar/);
	assert.match(manifest.interface.defaultPrompt[0], /Zotero Desktop XPI/i);
});
