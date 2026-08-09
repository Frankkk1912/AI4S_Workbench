import { z } from "zod";
import { defaultDataDir } from "./lib/paths.js";

export interface BrowserConfig {
	dataDir: string;
	channel: "chrome" | "chromium" | "chrome-cdp";
	cdpEndpoint: string;
	headless: false;
	idleTtlMinutes: number;
	diagnosticRetentionDays: number;
}

export function loadConfig(
	env: NodeJS.ProcessEnv = process.env,
): BrowserConfig {
	const parsed = z
		.object({
			LITERATURE_DATABASE_BROWSER_DATA_DIR: z.string().min(1).optional(),
			// Chromium has a process/profile boundary independent of the user's running Chrome.
			// This is required for a dedicated visible session on macOS, where Chrome can
			// hand a second launch to the existing application and drop Playwright's pipe.
			LITERATURE_DATABASE_BROWSER_CHANNEL: z
				.enum(["chrome", "chromium", "chrome-cdp"])
				.default("chromium"),
			LITERATURE_DATABASE_BROWSER_CDP_ENDPOINT: z
				.string()
				.url()
				.default("http://127.0.0.1:9222"),
			LITERATURE_DATABASE_BROWSER_HEADLESS: z
				.enum(["false", "0"])
				.default("false"),
			LITERATURE_DATABASE_BROWSER_IDLE_TTL_MINUTES: z.coerce
				.number()
				.int()
				.min(1)
				.max(240)
				.default(30),
			LITERATURE_DATABASE_BROWSER_DIAGNOSTIC_RETENTION_DAYS: z.coerce
				.number()
				.int()
				.min(1)
				.max(90)
				.default(7),
		})
		.parse(env);

	return {
		dataDir: parsed.LITERATURE_DATABASE_BROWSER_DATA_DIR ?? defaultDataDir(env),
		channel: parsed.LITERATURE_DATABASE_BROWSER_CHANNEL,
		cdpEndpoint: parsed.LITERATURE_DATABASE_BROWSER_CDP_ENDPOINT,
		headless: false,
		idleTtlMinutes: parsed.LITERATURE_DATABASE_BROWSER_IDLE_TTL_MINUTES,
		diagnosticRetentionDays:
			parsed.LITERATURE_DATABASE_BROWSER_DIAGNOSTIC_RETENTION_DAYS,
	};
}
