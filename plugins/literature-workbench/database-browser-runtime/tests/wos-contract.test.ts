import { chromium } from "playwright";
import { describe, expect, it } from "vitest";
import {
	clickUniqueVisibleButton,
	commitExactQuery,
	parseWosResultCount,
	WOS_PAGE_CONTRACT,
} from "../src/adapters/wos.js";
import { loadConfig } from "../src/config.js";

const RESULTS_FIXTURE = `
Results for TS=(cardiac fibrosis) AND PY=(2025)
688 results from Web of Science Core Collection for:
TS=(cardiac fibrosis) AND PY=(2025)
`;

describe("calibrated WoS page contract", () => {
	it("supports isolated browsers and an explicit existing-Chrome CDP mode", () => {
		expect(loadConfig({}).channel).toBe("chromium");
		expect(
			loadConfig({ LITERATURE_DATABASE_BROWSER_CHANNEL: "chrome" }).channel,
		).toBe("chrome");
		const cdp = loadConfig({
			LITERATURE_DATABASE_BROWSER_CHANNEL: "chrome-cdp",
		});
		expect(cdp.channel).toBe("chrome-cdp");
		expect(cdp.cdpEndpoint).toBe("http://127.0.0.1:9222");
	});

	it("uses the authorized Core Collection entrypoint and stable page controls", () => {
		expect(WOS_PAGE_CONTRACT.smartSearchUrl).toBe(
			"https://webofscience.clarivate.cn/wos/woscc/smart-search",
		);
		expect(WOS_PAGE_CONTRACT.queryEditor).toBe(
			"textarea#advancedSearchInputArea",
		);
		expect(WOS_PAGE_CONTRACT.exportTrigger).toBe("#export-trigger-btn");
		expect(WOS_PAGE_CONTRACT.tabDelimitedExport).toBe("#exportToTabWinButton");
		expect(WOS_PAGE_CONTRACT.exportDialog).toBe("app-export-out-details");
		expect(WOS_PAGE_CONTRACT.exportButton).toBe("#exportButton");
		expect(WOS_PAGE_CONTRACT.sortControl).toBe("#selectSortOption");
	});

	it("uses the calibrated native setter and bubbling input/change events", async () => {
		const browser = await chromium.launch({ headless: true });
		try {
			const page = await browser.newPage();
			await page.setContent(`
				<textarea id="advancedSearchInputArea"></textarea>
				<script>
					const editor = document.querySelector('#advancedSearchInputArea');
					editor.addEventListener('input', () => editor.dataset.inputSeen = 'true');
					editor.addEventListener('change', () => editor.dataset.changeSeen = 'true');
				</script>
			`);
			const editor = page.locator("#advancedSearchInputArea");
			expect(await commitExactQuery(editor, "TS=(cardiac fibrosis)")).toBe(
				true,
			);
			expect(await editor.inputValue()).toBe("TS=(cardiac fibrosis)");
			expect(await editor.getAttribute("data-input-seen")).toBe("true");
			expect(await editor.getAttribute("data-change-seen")).toBe("true");
		} finally {
			await browser.close();
		}
	});

	it("clicks the one visible exact Search button when a hidden duplicate exists", async () => {
		const browser = await chromium.launch({ headless: true });
		try {
			const page = await browser.newPage();
			await page.setContent(`
				<button style="display:none">Search</button>
				<button id="real-search" type="button"> Search </button>
				<script>
					document.querySelector('#real-search').addEventListener('click', () => {
						document.body.dataset.searchSubmitted = 'true';
					});
				</script>
			`);
			const result = await clickUniqueVisibleButton(page, "Search");
			expect(result).toEqual({ count: 1, disabled: false });
			expect(
				await page.locator("body").getAttribute("data-search-submitted"),
			).toBe("true");
		} finally {
			await browser.close();
		}
	});

	it("parses a verified Core Collection result count and rejects non-result text", () => {
		expect(parseWosResultCount(RESULTS_FIXTURE)).toBe(688);
		expect(
			parseWosResultCount("No result count was verified."),
		).toBeUndefined();
	});
});
