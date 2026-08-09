import { mkdir } from "node:fs/promises";
import { join } from "node:path";
import {
	chromium,
	type Browser,
	type BrowserContext,
	type Locator,
	type Page,
} from "playwright";
import type { BrowserConfig } from "../config.js";
import {
	DATABASE_ID,
	type BrowserAdapter,
	type ExportExecutionResult,
	type ExportInput,
	type Filters,
	type SearchExecutionResult,
	type SearchInput,
	type SessionSnapshot,
} from "../domain.js";
import { BrokerError } from "../errors.js";

export const WOS_PAGE_CONTRACT = {
	// Calibrated in an authorized, visible Core Collection session on 2026-07-31.
	smartSearchUrl: "https://webofscience.clarivate.cn/wos/woscc/smart-search",
	queryEditor: "textarea#advancedSearchInputArea",
	exportTrigger: "#export-trigger-btn",
	tabDelimitedExport: "#exportToTabWinButton",
	exportDialog: "app-export-out-details",
	exportButton: "#exportButton",
	sortControl: "#selectSortOption",
} as const;
const RESULTS_COUNT =
	/([\d,]+)\s+results from Web of Science Core Collection for:/i;
const DOCUMENT_TYPE_VALUES: Record<string, string> = {
	Article: "DT.ARTICLE",
	Review: "DT.REVIEW",
};

function session(
	sessionState: SessionSnapshot["sessionState"],
	message: string,
	errorCode?: SessionSnapshot["errorCode"],
): SessionSnapshot {
	return {
		database: DATABASE_ID,
		sessionState,
		userActionRequired:
			sessionState === "auth_required" ||
			sessionState === "manual_intervention_required",
		message,
		...(errorCode ? { errorCode } : {}),
		updatedAt: new Date().toISOString(),
	};
}

function pageText(page: Page): Promise<string> {
	return page
		.locator("body")
		.innerText({ timeout: 5_000 })
		.then((text) => text.toLowerCase());
}
export function parseWosResultCount(text: string): number | undefined {
	const match = RESULTS_COUNT.exec(text);
	return match?.[1] ? Number(match[1].replaceAll(",", "")) : undefined;
}

export async function clickUniqueVisibleButton(
	page: Page,
	label: string,
): Promise<{ count: number; disabled: boolean }> {
	return page.locator("button").evaluateAll((buttons, expectedLabel) => {
		const visible = buttons.filter((button) => {
			const box = button.getBoundingClientRect();
			const style = getComputedStyle(button);
			return (
				button.textContent?.trim() === expectedLabel &&
				box.width > 0 &&
				box.height > 0 &&
				style.display !== "none" &&
				style.visibility !== "hidden"
			);
		});
		const target = visible[0] as HTMLButtonElement | undefined;
		const disabled = target?.disabled ?? false;
		// This exact DOM click is the calibrated successful Chrome/CDP path.
		if (visible.length === 1 && target && !disabled) target.click();
		return { count: visible.length, disabled };
	}, label);
}

export async function commitExactQuery(
	editor: Locator,
	value: string,
): Promise<boolean> {
	// Exact 2026-07-31 successful Chrome sequence: set the Angular textarea via
	// its native setter, then emit bubbling input/change events. Do not introduce
	// a Playwright click or keyboard event before this sequence.
	await editor.evaluate((element, query) => {
		const setter = Object.getOwnPropertyDescriptor(
			HTMLTextAreaElement.prototype,
			"value",
		)?.set;
		if (!setter) throw new Error("textarea value setter unavailable");
		setter.call(element, query);
		element.dispatchEvent(
			new InputEvent("input", {
				bubbles: true,
				inputType: "insertText",
				data: query,
			}),
		);
		element.dispatchEvent(new Event("change", { bubbles: true }));
	}, value);
	return (await editor.inputValue()) === value;
}

function requiresAuthentication(url: string, text: string): boolean {
	return (
		url.includes("access.clarivate.com/login") ||
		[
			"sign in to continue with web of science",
			"institutional sign in",
			"登录以继续使用 web of science",
		].some((marker) => text.includes(marker))
	);
}

/** Calibrated 2026-07-31 against an authorized, visible WoS Core Collection session. */
export class WosPlaywrightAdapter implements BrowserAdapter {
	private browser: Browser | undefined;
	private context: BrowserContext | undefined;
	private ownedPage: Page | undefined;

	constructor(private readonly config: BrowserConfig) {}

	async openSession(): Promise<SessionSnapshot> {
		try {
			const page = await this.openSmartSearch();
			const text = await pageText(page);
			if (text.includes("captcha") || text.includes("verify you are human"))
				return session(
					"manual_intervention_required",
					"Complete the visible WoS verification challenge, then call database_session_open again.",
					"CAPTCHA_OR_CHALLENGE",
				);
			if (requiresAuthentication(page.url(), text))
				return session(
					"auth_required",
					"Complete institution authentication in the visible WoS window, then call database_session_open again.",
					"AUTH_REQUIRED",
				);
			if (
				text.includes("no subscription") ||
				text.includes("not entitled") ||
				text.includes("access denied")
			)
				return session(
					"auth_required",
					"WoS access is not available on this network. Connect to an authorized campus network, then retry.",
					"CAMPUS_ACCESS_REQUIRED",
				);
			await page
				.getByText("Web of Science Core Collection", { exact: true })
				.waitFor({ state: "visible", timeout: 15_000 })
				.catch(() => undefined);
			if (!(await this.hasCoreCollectionEntry(page)))
				return session(
					"manual_intervention_required",
					"The visible WoS page could not be safely recognized as Core Collection Smart Search.",
					"PAGE_CONTRACT_CHANGED",
				);
			return session("ready", "WoS Core Collection Smart Search is ready.");
		} catch (error) {
			return session(
				"unavailable",
				`Could not open the visible WoS browser: ${error instanceof Error ? error.message : String(error)}`,
				"BROWSER_CLOSED",
			);
		}
	}

	async sessionStatus(): Promise<SessionSnapshot> {
		const page = this.ownedPage;
		if (!page || page.isClosed())
			return session("closed", "No WoS browser session is open.");
		if (
			!/https:\/\/(webofscience\.clarivate\.cn|www\.webofscience\.com)\//.test(
				page.url(),
			)
		)
			return session(
				"stale",
				"The browser is no longer on an allowed WoS page.",
				"BROWSER_CLOSED",
			);
		const text = await pageText(page).catch(() => "");
		if (requiresAuthentication(page.url(), text))
			return session(
				"auth_required",
				"Complete institution authentication in the visible WoS window, then call database_session_open again.",
				"AUTH_REQUIRED",
			);
		if (!text.includes("web of science core collection"))
			return session(
				"stale",
				"The current WoS page no longer confirms Core Collection access.",
				"PAGE_CONTRACT_CHANGED",
			);
		return session("ready", "WoS browser session is open.");
	}

	async executeSearch(input: SearchInput): Promise<SearchExecutionResult> {
		const page = await this.requireReadyPage();
		await this.openQueryBuilder(page);
		const editor = page.locator(WOS_PAGE_CONTRACT.queryEditor);
		// Use the exact successful Chrome calibration sequence; the post-input
		// pause allows WoS/Angular to commit its model before Search is invoked.
		if (!(await commitExactQuery(editor, input.query.value)))
			throw new BrokerError(
				"QUERY_NOT_COMMITTED",
				"WoS did not retain the exact Advanced Search query after native input.",
				true,
			);
		await page.waitForTimeout(2_000);
		const submit = await clickUniqueVisibleButton(page, "Search");
		if (submit.count !== 1 || submit.disabled)
			throw new BrokerError(
				"QUERY_NOT_COMMITTED",
				`The Query Builder requires one visible, enabled Search button; found ${submit.count}${submit.disabled ? " (disabled)" : ""}.`,
				true,
			);
		await this.waitForSearchOutcome(page);
		let text = await pageText(page);
		if (parseWosResultCount(text) === undefined)
			throw new BrokerError(
				"RESULTS_NOT_VERIFIED",
				"WoS did not expose a verified Core Collection result count.",
				true,
			);
		await this.applyFilters(page, input.filters);
		await this.applySort(page, input.sort ?? "relevance");
		text = await pageText(page);
		const count = parseWosResultCount(text);
		if (count === undefined)
			throw new BrokerError(
				"RESULTS_NOT_VERIFIED",
				"WoS result count disappeared after filters or sort.",
				true,
			);
		return {
			reportedResultCount: count,
			appliedFilters: input.filters ?? {},
			appliedSort: input.sort ?? "relevance",
		};
	}

	async executeExport(
		input: ExportInput,
		exportDirectory: string,
	): Promise<ExportExecutionResult> {
		const page = await this.requireReadyPage();
		const count = parseWosResultCount(await pageText(page));
		if (count === undefined)
			throw new BrokerError(
				"JOB_NOT_EXPORTABLE",
				"WoS is not displaying a verified results page.",
			);
		const end = Math.min(input.limit, count);
		await page.locator(WOS_PAGE_CONTRACT.exportTrigger).click();
		await page.locator(WOS_PAGE_CONTRACT.tabDelimitedExport).click();
		const dialog = page.locator(WOS_PAGE_CONTRACT.exportDialog);
		await dialog
			.locator('input[name="outputMethodType"][value="fromRange"]')
			.check();
		await dialog.locator('input[name="markFrom"]').fill("1");
		await dialog.locator('input[name="markTo"]').fill(String(end));
		const content = dialog.locator('button[role="combobox"]');
		await content.click();
		await page
			.getByRole("option", { name: "Full Record", exact: true })
			.click();
		if ((await content.innerText()).trim() !== "Full Record")
			throw new BrokerError(
				"DOWNLOAD_INVALID",
				"WoS did not retain the required Full Record export content.",
				true,
			);
		await mkdir(exportDirectory, { recursive: true, mode: 0o700 });
		const downloadPromise = page.waitForEvent("download", { timeout: 45_000 });
		await dialog.locator(WOS_PAGE_CONTRACT.exportButton).click();
		const download = await downloadPromise;
		const path = join(exportDirectory, "batch-0001.txt");
		await download.saveAs(path);
		return { artifacts: [{ path, rangeStart: 1, rangeEnd: end }] };
	}

	async close(): Promise<void> {
		if (this.ownedPage && !this.ownedPage.isClosed())
			await this.ownedPage.close().catch(() => undefined);
		this.ownedPage = undefined;
		if (this.config.channel !== "chrome-cdp") {
			await this.context?.close();
			this.context = undefined;
			this.browser = undefined;
		}
	}

	private async waitForSearchOutcome(page: Page): Promise<void> {
		let outcome: string;
		try {
			const handle = await page.waitForFunction(
				`() => {
					const path = location.pathname;
					const text = document.body?.innerText.toLowerCase() ?? "";
					if (path.includes("/wos/woscc/summary/")) return "results";
					if (text.includes("captcha") || text.includes("verify you are human")) return "challenge";
					if (location.href.includes("access.clarivate.com/login") || text.includes("sign in to continue with web of science")) return "auth";
					return false;
				}`,
				undefined,
				{ timeout: 60_000 },
			);
			const value = await handle.jsonValue();
			if (typeof value !== "string")
				throw new BrokerError(
					"RESULTS_NOT_VERIFIED",
					"WoS returned a non-string search outcome.",
					true,
				);
			outcome = value;
		} catch {
			if (page.isClosed())
				throw new BrokerError(
					"BROWSER_CLOSED",
					"The visible WoS browser closed while waiting for search results.",
					true,
				);
			const path = new URL(page.url()).pathname;
			throw new BrokerError(
				"RESULTS_NOT_VERIFIED",
				`WoS did not produce a results page within 60 seconds after the exact visible Search click (current path: ${path}).`,
				true,
			);
		}
		if (outcome === "challenge")
			throw new BrokerError(
				"CAPTCHA_OR_CHALLENGE",
				"Complete the visible WoS verification challenge, then submit a new idempotent search request.",
				true,
			);
		if (outcome === "auth")
			throw new BrokerError(
				"AUTH_REQUIRED",
				"Complete institution authentication in the visible WoS window, then submit a new search request.",
				true,
			);
		if (outcome !== "results")
			throw new BrokerError(
				"RESULTS_NOT_VERIFIED",
				`Unexpected WoS search outcome: ${outcome}.`,
				true,
			);
	}

	private async openSmartSearch(): Promise<Page> {
		if (this.ownedPage && !this.ownedPage.isClosed()) {
			await this.ownedPage.goto(WOS_PAGE_CONTRACT.smartSearchUrl, {
				waitUntil: "domcontentloaded",
				timeout: 45_000,
			});
			return this.ownedPage;
		}

		if (this.config.channel === "chrome-cdp") {
			if (!this.browser?.isConnected())
				this.browser = await chromium.connectOverCDP(this.config.cdpEndpoint);
			this.context = this.browser.contexts()[0];
			if (!this.context)
				throw new Error("Chrome CDP connection exposed no browser context.");
			// Never navigate or close a user-owned tab. The MCP owns only this page.
			this.ownedPage = await this.context.newPage();
		} else {
			const profileDir = join(this.config.dataDir, "profiles", DATABASE_ID);
			await mkdir(profileDir, { recursive: true, mode: 0o700 });
			this.context = await chromium.launchPersistentContext(profileDir, {
				channel: this.config.channel,
				headless: false,
				acceptDownloads: true,
				viewport: null,
			});
			this.ownedPage =
				this.context.pages().find((candidate) => !candidate.isClosed()) ??
				(await this.context.newPage());
		}
		await this.ownedPage.goto(WOS_PAGE_CONTRACT.smartSearchUrl, {
			waitUntil: "domcontentloaded",
			timeout: 45_000,
		});
		return this.ownedPage;
	}

	private async requireReadyPage(): Promise<Page> {
		const snapshot = await this.openSession();
		if (snapshot.sessionState !== "ready")
			throw new BrokerError(
				snapshot.errorCode ?? "PAGE_CONTRACT_CHANGED",
				snapshot.message,
				snapshot.userActionRequired,
			);
		const page = this.ownedPage;
		if (!page || page.isClosed())
			throw new BrokerError(
				"BROWSER_CLOSED",
				"The WoS browser session closed before the action began.",
				true,
			);
		return page;
	}

	private async hasCoreCollectionEntry(page: Page): Promise<boolean> {
		return page
			.getByText("Web of Science Core Collection", { exact: true })
			.isVisible()
			.catch(() => false);
	}

	private async openQueryBuilder(page: Page): Promise<void> {
		const advanced = page
			.locator("#snAdvancedLink")
			.or(page.getByText("Advanced Search", { exact: true }))
			.first();
		await advanced.click();
		const builder = page.getByText("QUERY BUILDER", { exact: true });
		await builder.click();
		await page
			.locator("textarea#advancedSearchInputArea")
			.waitFor({ state: "visible", timeout: 15_000 });
		// Visibility alone fires before the Query Builder's form binding settles.
		await page.waitForTimeout(1_000);
	}

	private async applyFilters(
		page: Page,
		filters: Filters | undefined,
	): Promise<void> {
		if (
			!filters ||
			(!filters.documentTypes?.length &&
				filters.fromYear === undefined &&
				filters.untilYear === undefined)
		)
			return;
		const years =
			filters.fromYear === undefined || filters.untilYear === undefined
				? []
				: Array.from(
						{ length: filters.untilYear - filters.fromYear + 1 },
						(_, index) => filters.untilYear! - index,
					);
		for (const year of years)
			await page.locator(`input[name="PY"][value="PY.${year}"]`).check();
		for (const type of filters.documentTypes ?? []) {
			const value = DOCUMENT_TYPE_VALUES[type];
			if (!value)
				throw new BrokerError(
					"FILTER_NOT_APPLIED",
					`WoS V1 supports only Article and Review document-type filters; received ${type}.`,
					true,
				);
			await page.locator(`input[name="DT"][value="${value}"]`).check();
		}
		const beforeRefine = page.url();
		await page.getByRole("button", { name: "Refine", exact: true }).click();
		await page.waitForFunction(
			"(previous) => location.pathname.includes('/wos/woscc/summary/') && location.href !== previous",
			beforeRefine,
			{ timeout: 45_000 },
		);
	}

	private async applySort(
		page: Page,
		sort: NonNullable<SearchInput["sort"]>,
	): Promise<void> {
		const option: Record<NonNullable<SearchInput["sort"]>, string> = {
			relevance: "relevance",
			"date-desc": "date-descending",
			"citations-desc": "times-cited-descending",
		};
		await page.locator(WOS_PAGE_CONTRACT.sortControl).click();
		await page.locator(`#${option[sort]}`).click();
		await page.waitForFunction(
			"(expectedPath) => location.pathname.endsWith(expectedPath)",
			`/${option[sort]}/1`,
			{ timeout: 20_000 },
		);
		const expected = {
			relevance: "Relevance",
			"date-desc": "Date: newest first",
			"citations-desc": "Citations: highest first",
		}[sort];
		if (
			(await page.locator(WOS_PAGE_CONTRACT.sortControl).innerText()).trim() !==
			expected
		)
			throw new BrokerError(
				"FILTER_NOT_APPLIED",
				`WoS did not retain the requested ${expected} sort.`,
				true,
			);
	}
}
