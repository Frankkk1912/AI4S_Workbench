#!/usr/bin/env node
/**
 * First-run credential onboarding for Literature Workbench.
 *
 * Secrets are accepted only through a masked local TTY prompt. Reports and
 * onboarding state contain capability/status metadata only.
 */
import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { posix, resolve, win32 } from "node:path";
import { fileURLToPath } from "node:url";
import {
	envKeyExists,
	linePrompt,
	maskedPrompt,
	readJsonObject,
	updateEnvKey,
	writeJsonPrivate,
	writePrivateFile,
} from "../runtime/scripts/credential-utils.mjs";

export const ZOTERO_XPI_ONBOARDING = {
	status: "manual_install_required",
	purpose:
		"Display AI4S literature metrics, Agent Tags, AI Summary, and the interactive Priority control in Zotero Desktop.",
	artifact: "source/literature-metrics/dist/literature-metrics-<version>.xpi",
	install:
		"In Zotero Desktop, open Tools → Add-ons, choose the gear menu, then Install Add-on From File… and select the built XPI.",
	note: "The credential wizard and MCP never install or modify Zotero Desktop add-ons automatically.",
};

export const PROVIDERS = {
	zotero: {
		label: "Zotero Web API",
		apply_url: "https://www.zotero.org/settings/keys",
		purpose:
			"cloud library identity, item/tag writes, and optional file access",
	},
	pubmed: {
		label: "PubMed / NCBI",
		apply_url: "https://www.ncbi.nlm.nih.gov/datasets/docs/v2/api/api-keys/",
		purpose:
			"higher E-utilities request allowance and more stable batch retrieval",
	},
	easyscholar: {
		label: "EasyScholar",
		apply_url: "https://www.easyscholar.cc/",
		purpose: "optional journal rank and metric enrichment",
	},
};

export function onboardingPaths(
	env = process.env,
	platform = process.platform,
	home = homedir(),
) {
	const platformPath = platform === "win32" ? win32 : posix;
	let workbenchDir;
	let academicConfig;
	if (platform === "win32") {
		const local =
			env.LOCALAPPDATA?.trim() || platformPath.join(home, "AppData", "Local");
		workbenchDir = platformPath.join(local, "literature-workbench");
		academicConfig = platformPath.join(
			local,
			"frank-ai4s",
			"academic-research.json",
		);
	} else if (platform === "darwin") {
		workbenchDir = platformPath.join(
			home,
			"Library",
			"Application Support",
			"literature-workbench",
		);
		academicConfig = platformPath.join(
			home,
			".config",
			"frank-ai4s",
			"academic-research.json",
		);
	} else {
		const configHome =
			env.XDG_CONFIG_HOME?.trim() || platformPath.join(home, ".config");
		workbenchDir = platformPath.join(configHome, "literature-workbench");
		academicConfig = platformPath.join(
			configHome,
			"frank-ai4s",
			"academic-research.json",
		);
	}
	return {
		zoteroEnv:
			env.LITERATURE_ZOTERO_MCP_ENV_FILE?.trim() ||
			platformPath.join(workbenchDir, "zotero.env"),
		academicConfig: env.AI4S_ACADEMIC_CONFIG_FILE?.trim() || academicConfig,
		legacyZoteroEnv: platformPath.join(
			home,
			".config",
			"ai4s-literature-workbench",
			"zotero.env",
		),
		legacyAcademicConfig: platformPath.join(
			home,
			".config",
			"frank-ai4s",
			"academic-research.json",
		),
		state:
			env.AI4S_ONBOARDING_STATE_FILE?.trim() ||
			platformPath.join(workbenchDir, "onboarding.json"),
	};
}

function academicKeyConfigured(
	path,
	legacyPath,
	configName,
	envName,
	env = process.env,
) {
	if (env[envName]?.trim()) return { configured: true, source: "environment" };
	const sourcePath = existsSync(path) ? path : legacyPath;
	const config = readJsonObject(sourcePath);
	return {
		configured: Boolean(String(config[configName] ?? "").trim()),
		source: String(config[configName] ?? "").trim() ? "private_config" : "none",
	};
}

export function redactedStatus(paths = onboardingPaths(), env = process.env) {
	const state = readJsonObject(paths.state);
	const zoteroConfigured =
		Boolean(env.ZOTERO_API_KEY?.trim()) ||
		envKeyExists(paths.zoteroEnv, "ZOTERO_API_KEY") ||
		envKeyExists(paths.legacyZoteroEnv, "ZOTERO_API_KEY");
	const pubmed = academicKeyConfigured(
		paths.academicConfig,
		paths.legacyAcademicConfig,
		"pubmed_api_key",
		"PUBMED_API_KEY",
		env,
	);
	const easyscholar = academicKeyConfigured(
		paths.academicConfig,
		paths.legacyAcademicConfig,
		"easyscholar_secret_key",
		"EASYSCHOLAR_SECRET_KEY",
		env,
	);
	return {
		schema_version: 1,
		first_run: !state.offered_at,
		onboarding_completed: Boolean(state.completed_at),
		baseline_available: true,
		providers: {
			zotero: {
				configured: zoteroConfigured,
				source: env.ZOTERO_API_KEY?.trim()
					? "environment"
					: zoteroConfigured
						? "private_config"
						: "none",
				optional: true,
			},
			pubmed: { ...pubmed, optional: true },
			easyscholar: { ...easyscholar, optional: true },
		},
		application_links: Object.fromEntries(
			Object.entries(PROVIDERS).map(([name, provider]) => [
				name,
				provider.apply_url,
			]),
		),
		zotero_desktop_xpi: ZOTERO_XPI_ONBOARDING,
		privacy: "No credential values are included in this report.",
	};
}

function saveAcademicKey(path, legacyPath, name, key) {
	const sourcePath = existsSync(path) ? path : legacyPath;
	const config = readJsonObject(sourcePath);
	config[name] = key;
	writeJsonPrivate(path, config);
}

function saveZoteroKey(path, legacyPath, key) {
	const sourcePath = existsSync(path) ? path : legacyPath;
	const existing = existsSync(sourcePath)
		? readFileSync(sourcePath, "utf8")
		: "";
	writePrivateFile(path, updateEnvKey(existing, "ZOTERO_API_KEY", key));
}

async function fetchJson(url, options, provider, fetchImpl = fetch) {
	for (let attempt = 0; attempt < 3; attempt += 1) {
		try {
			const response = await fetchImpl(url, options);
			const text = await response.text();
			if (response.status === 429) {
				throw new Error(
					`${provider} rate limit reached (HTTP 429); retry later.`,
				);
			}
			if (response.status >= 500 && attempt < 2) {
				await new Promise((resolveWait) =>
					setTimeout(resolveWait, 2 ** attempt * 1000),
				);
				continue;
			}
			if (!response.ok) {
				throw new Error(
					`${provider} rejected the credential (HTTP ${response.status}).`,
				);
			}
			try {
				return JSON.parse(text);
			} catch {
				throw new Error(
					`${provider} returned an unexpected non-JSON response.`,
				);
			}
		} catch (error) {
			const message = error instanceof Error ? error.message : String(error);
			if (/rejected|rate limit|unexpected non-JSON/.test(message)) throw error;
			if (attempt < 2) {
				await new Promise((resolveWait) =>
					setTimeout(resolveWait, 2 ** attempt * 1000),
				);
			}
		}
	}
	throw new Error(
		`${provider} could not be reached; the existing configuration was not changed.`,
	);
}

export async function verifyZoteroKey(key, fetchImpl = fetch) {
	const info = await fetchJson(
		"https://api.zotero.org/keys/current",
		{ headers: { "Zotero-API-Key": key } },
		"Zotero",
		fetchImpl,
	);
	if (!Number.isInteger(info.userID) || !info.username) {
		throw new Error("Zotero returned an unexpected key-validation response.");
	}
	const access = info.access?.user ?? {};
	return {
		library: Boolean(access.library),
		write: Boolean(access.write),
		files: Boolean(access.files),
		notes: Boolean(access.notes),
		groups: Object.keys(info.access?.groups ?? {}).length,
	};
}

export async function verifyPubmedKey(key, fetchImpl = fetch) {
	const params = new URLSearchParams({
		db: "pubmed",
		retmode: "json",
		api_key: key,
	});
	const data = await fetchJson(
		`https://eutils.ncbi.nlm.nih.gov/entrez/eutils/einfo.fcgi?${params}`,
		{ headers: { "User-Agent": "AI4S-Literature-Workbench/onboarding" } },
		"PubMed",
		fetchImpl,
	);
	if (!data.einforesult)
		throw new Error("PubMed returned an unexpected key-validation response.");
	return { valid: true };
}

export async function verifyEasyScholarKey(key, fetchImpl = fetch) {
	const params = new URLSearchParams({
		publicationName: "Nature",
		secretKey: key,
	});
	const data = await fetchJson(
		`https://www.easyscholar.cc/open/getPublicationRank?${params}`,
		{ headers: { "User-Agent": "AI4S-Literature-Workbench/onboarding" } },
		"EasyScholar",
		fetchImpl,
	);
	if (data.code !== 200 || !data.data || typeof data.data !== "object") {
		throw new Error("EasyScholar rejected the credential.");
	}
	return { valid: true };
}

async function configureProvider(provider, paths, fetchImpl = fetch) {
	const definition = PROVIDERS[provider];
	process.stdout.write(
		`\n${definition.label}\n用途: ${definition.purpose}\n申请: ${definition.apply_url}\n`,
	);
	const key = String(
		await maskedPrompt(`Paste ${definition.label} key (input hidden): `),
	).trim();
	if (!key || /[\r\n]/.test(key))
		throw new Error("The key must be a single non-empty line.");

	let capabilities = {};
	if (provider === "zotero") {
		capabilities = await verifyZoteroKey(key, fetchImpl);
		saveZoteroKey(paths.zoteroEnv, paths.legacyZoteroEnv, key);
	} else if (provider === "pubmed") {
		capabilities = await verifyPubmedKey(key, fetchImpl);
		saveAcademicKey(
			paths.academicConfig,
			paths.legacyAcademicConfig,
			"pubmed_api_key",
			key,
		);
	} else {
		capabilities = await verifyEasyScholarKey(key, fetchImpl);
		saveAcademicKey(
			paths.academicConfig,
			paths.legacyAcademicConfig,
			"easyscholar_secret_key",
			key,
		);
	}
	return { status: "configured", capabilities };
}

async function configureWithRetry(provider, paths) {
	while (true) {
		try {
			return await configureProvider(provider, paths);
		} catch (error) {
			process.stderr.write(
				`${PROVIDERS[provider].label}: ${error instanceof Error ? error.message : String(error)}\n`,
			);
			const choice = String(
				await linePrompt("Retry? [r]etry / [s]kip: "),
			).toLowerCase();
			if (choice !== "r" && choice !== "retry") return { status: "skipped" };
		}
	}
}

function writeZoteroXpiReminder() {
	process.stdout.write(
		`\nZotero Desktop add-on required for the AI4S columns and Priority control:\n${ZOTERO_XPI_ONBOARDING.install}\nXPI: ${ZOTERO_XPI_ONBOARDING.artifact}\n`,
	);
}

async function setup(paths, onlyProvider) {
	const results = {};
	const providers = onlyProvider ? [onlyProvider] : Object.keys(PROVIDERS);
	for (const provider of providers) {
		const current = redactedStatus(paths).providers[provider];
		const prompt = current.configured
			? `${PROVIDERS[provider].label} is already configured. Reconfigure it? [y/N]: `
			: `Configure ${PROVIDERS[provider].label} now? [y/N]: `;
		const choice = String(await linePrompt(prompt)).toLowerCase();
		if (choice !== "y" && choice !== "yes") {
			results[provider] = {
				status: current.configured ? "unchanged" : "skipped",
			};
			continue;
		}
		results[provider] = await configureWithRetry(provider, paths);
	}
	const state = readJsonObject(paths.state);
	const now = new Date().toISOString();
	state.schema_version = 1;
	state.offered_at ||= now;
	state.completed_at = now;
	state.last_results = Object.fromEntries(
		Object.entries(results).map(([provider, result]) => [
			provider,
			result.status,
		]),
	);
	writeJsonPrivate(paths.state, state);
	if (!onlyProvider || onlyProvider === "zotero") writeZoteroXpiReminder();
	return { ...redactedStatus(paths), setup_results: results };
}

function parseArgs(argv) {
	const command = argv[0];
	if (!["status", "setup", "reconfigure"].includes(command)) {
		throw new Error(
			"Usage: node scripts/onboard.mjs <status|setup|reconfigure> --output <result.json> [--provider zotero|pubmed|easyscholar] [--mark-offered]",
		);
	}
	const parsed = { command, markOffered: false };
	for (let index = 1; index < argv.length; index += 1) {
		const token = argv[index];
		if (token === "--mark-offered") parsed.markOffered = true;
		else if (token === "--output") parsed.output = argv[++index];
		else if (token === "--provider") parsed.provider = argv[++index];
		else throw new Error(`Unknown argument: ${token}`);
	}
	if (!parsed.output) throw new Error("--output is required.");
	if (command === "reconfigure" && !PROVIDERS[parsed.provider]) {
		throw new Error(
			"--provider must be zotero, pubmed, or easyscholar for reconfigure.",
		);
	}
	return parsed;
}

export async function main(argv = process.argv.slice(2)) {
	const args = parseArgs(argv);
	const paths = onboardingPaths();
	let report;
	if (args.command === "status") {
		if (args.markOffered) {
			const state = readJsonObject(paths.state);
			state.schema_version = 1;
			state.offered_at ||= new Date().toISOString();
			writeJsonPrivate(paths.state, state);
		}
		report = redactedStatus(paths);
	} else {
		report = await setup(
			paths,
			args.command === "reconfigure" ? args.provider : undefined,
		);
	}
	writeJsonPrivate(resolve(args.output), report);
	process.stdout.write(
		`Success! Redacted onboarding result written to: ${resolve(args.output)}\n`,
	);
}

const isMain =
	process.argv[1] &&
	resolve(process.argv[1]) === resolve(fileURLToPath(import.meta.url));
if (isMain) {
	main().catch((error) => {
		process.stderr.write(
			`Onboarding failed: ${error instanceof Error ? error.message : String(error)}\n`,
		);
		process.exitCode = 1;
	});
}
