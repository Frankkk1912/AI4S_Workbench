import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import {
	chmodSync,
	existsSync,
	mkdtempSync,
	mkdirSync,
	readFileSync,
	rmSync,
	symlinkSync,
	writeFileSync,
} from "node:fs";
import { homedir } from "node:os";
import { resolve } from "node:path";
import test from "node:test";

const root = resolve(import.meta.dirname, "..");
const windowsEntrypoint = resolve(root, "scripts", "Start-AI4S-Workbench.ps1");
const wslEntrypoint = resolve(root, "scripts", "setup-wsl-workbench.sh");

function runBash(args, options = {}) {
	return spawnSync("bash", [wslEntrypoint, ...args], {
		cwd: options.cwd ?? root,
		env: { ...process.env, ...options.env },
		encoding: "utf8",
	});
}

function simulateSupportedWsl2(t, bin) {
	if (process.platform !== "linux") {
		t.skip("Requires a Linux host to simulate the WSL2 filesystem contract");
		return null;
	}
	const osReleasePath = "/etc/os-release";
	if (!existsSync(osReleasePath)) {
		t.skip("Host does not expose /etc/os-release for the WSL2 simulation");
		return null;
	}
	const osRelease = readFileSync(osReleasePath, "utf8");
	if (
		!/^ID=ubuntu$/m.test(osRelease) ||
		!/^VERSION_ID="22\.04"$/m.test(osRelease)
	) {
		t.skip("Requires Ubuntu 22.04 to simulate the supported WSL2 host");
		return null;
	}
	const fakeUname = resolve(bin, "uname");
	writeFileSync(
		fakeUname,
		"#!/bin/sh\nprintf '5.15.153.1-microsoft-standard-WSL2\\n'\n",
	);
	chmodSync(fakeUname, 0o755);
	return {
		PATH: `${bin}:${process.env.PATH}`,
		WSL_DISTRO_NAME: "Ubuntu-22.04",
	};
}

test("Windows preflight is a create-new, diagnostic-only handoff", () => {
	assert.equal(existsSync(windowsEntrypoint), true);
	const script = readFileSync(windowsEntrypoint, "utf8");
	assert.match(script, /Windows 11/);
	assert.match(script, /Ubuntu-22\.04/);
	assert.match(script, /\$Distribution -cne "Ubuntu-22\.04"/);
	assert.match(script, /windows_wsl_preflight/);
	assert.match(script, /wsl\.exe/);
	assert.match(script, /onboarding-preflight\.json/);
	assert.match(script, /onboarding-preflight\.md/);
	assert.match(script, /wsl --install -d Ubuntu-22\.04/);
	assert.match(script, /FileMode\]::CreateNew/);
	assert.match(script, /UTF8Encoding\]::new\(\$false\)/);
	assert.match(script, /Where-Object \{ \$_ -ceq \$DistributionName \}/);
	assert.match(script, /Get-ReadableCommandEvidence/);
	assert.match(
		script,
		/Add-Check "wsl" "pass" "WSL is available\." "wsl\.exe --status exited with code 0\."/,
	);
	assert.match(script, /no readable diagnostic text was captured/);
	assert.doesNotMatch(
		script,
		/Add-Check "wsl" (?:"pass"|"action-needed")[^\n]+\$status\.output/,
	);
	const ignore = readFileSync(resolve(root, ".gitignore"), "utf8");
	assert.match(ignore, /^ai4s-onboarding-\*\/$/m);
	assert.doesNotMatch(script, /New-Item[^\n]+-Force|Set-Content/);
	assert.doesNotMatch(script, /Start-Process[^\n]+-Verb\s+RunAs/i);
	assert.doesNotMatch(
		script,
		/Restart-Computer|Enable-WindowsOptionalFeature|Disable-WindowsOptionalFeature/i,
	);
	assert.doesNotMatch(
		script,
		/(?:winget|choco)\s+install|docker\s+pull|nvidia-ctk/i,
	);
	assert.doesNotMatch(script, /Invoke-Expression|\biex\b/i);
});

test("PowerShell parser and exact-distribution pure function contract pass when PowerShell is available", (t) => {
	const discover = spawnSync(
		"bash",
		["-lc", "command -v powershell.exe || command -v pwsh"],
		{
			encoding: "utf8",
		},
	);
	if (discover.status !== 0 || !discover.stdout.trim()) {
		t.skip("PowerShell is unavailable on this test host");
		return;
	}
	const executable =
		process.platform === "win32" ? "powershell.exe" : discover.stdout.trim();
	let scriptPath = windowsEntrypoint;
	if (executable.endsWith("powershell.exe") && process.platform !== "win32") {
		const converted = spawnSync("wslpath", ["-w", windowsEntrypoint], {
			encoding: "utf8",
		});
		assert.equal(converted.status, 0, converted.stderr);
		scriptPath = converted.stdout.trim();
	}
	const quotedPath = scriptPath.replaceAll("'", "''");
	const command = [
		"$tokens=$null; $errors=$null",
		`$ast=[System.Management.Automation.Language.Parser]::ParseFile('${quotedPath}', [ref]$tokens, [ref]$errors)`,
		"if ($errors.Count -ne 0) { $errors | Out-String | Write-Error; exit 10 }",
		"$names=@('Get-ReadableCommandEvidence','Get-CleanWslLines','Get-ExactWslDistribution')",
		"$functions=$ast.FindAll({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $names -contains $node.Name}, $true)",
		"if ($functions.Count -ne 3) { exit 11 }",
		". ([ScriptBlock]::Create(($functions | ForEach-Object { $_.Extent.Text }) -join [Environment]::NewLine))",
		'$exact=Get-ExactWslDistribution "Ubuntu-22.04`n" "  NAME STATE VERSION`n* Ubuntu-22.04 Running 2`n" \'Ubuntu-22.04\'',
		'$backup=Get-ExactWslDistribution "Ubuntu-22.04-backup`n" "* Ubuntu-22.04-backup Running 2`n" \'Ubuntu-22.04\'',
		"if (-not $exact.installed -or $exact.version -ne 2 -or $backup.installed) { exit 12 }",
		"$fallback='wsl.exe --status exited with code 1; no readable diagnostic text was captured.'",
		'$dirty=Get-ReadableCommandEvidence ("unreadable" + [char]0 + "output") $fallback',
		"$clean=Get-ReadableCommandEvidence 'Access denied (0x800704ec).' $fallback",
		"if ($dirty -ne $fallback -or $clean -ne 'Access denied (0x800704ec).') { exit 13 }",
	].join("; ");
	const result = spawnSync(executable, ["-NoProfile", "-Command", command], {
		encoding: "utf8",
	});
	assert.equal(result.status, 0, result.stderr || result.stdout);
});

test("WSL initializer help and argument errors have executable CLI contracts", () => {
	const help = runBash(["--help"]);
	assert.equal(help.status, 0, help.stderr);
	assert.match(help.stdout, /--output-dir/);
	assert.match(help.stdout, /must not already exist/);

	for (const [args, expected] of [
		[[], /Choose exactly one/],
		[["--agent", "other"], /Choose exactly one/],
		[["--unknown"], /Unknown option/],
	]) {
		const result = runBash(args);
		assert.equal(result.status, 2, result.stderr);
		assert.match(result.stderr, expected);
	}
});

test("WSL initializer rejects a non-WSL kernel before creating outputs", () => {
	const fixture = mkdtempSync(resolve(homedir(), ".ai4s-non-wsl-test-"));
	try {
		const bin = resolve(fixture, "bin");
		mkdirSync(bin);
		const fakeUname = resolve(bin, "uname");
		writeFileSync(fakeUname, "#!/bin/sh\nprintf '6.8.0-generic\\n'\n");
		chmodSync(fakeUname, 0o755);
		const result = runBash(["--agent", "codex"], {
			env: { PATH: `${bin}:${process.env.PATH}` },
		});
		assert.equal(result.status, 2, result.stderr);
		assert.match(result.stderr, /only inside WSL2/);
	} finally {
		rmSync(fixture, { recursive: true, force: true });
	}
});

test("WSL initializer pins the plugin project from a foreign cwd and records onboarding failure", (t) => {
	const fixture = mkdtempSync(resolve(homedir(), ".ai4s-locked-project-test-"));
	try {
		const bin = resolve(fixture, "bin");
		const workspace = resolve(fixture, "workspace with spaces");
		const output = resolve(workspace, "run output");
		const environment = resolve(workspace, "environment evidence");
		const capture = resolve(fixture, "uv-argv.txt");
		mkdirSync(bin);
		const wslSimulation = simulateSupportedWsl2(t, bin);
		if (!wslSimulation) return;
		const fakeUv = resolve(bin, "uv");
		writeFileSync(
			fakeUv,
			'#!/bin/sh\nprintf \'%s\\n\' "$@" > "$AI4S_CAPTURE"\nexit 37\n',
		);
		chmodSync(fakeUv, 0o755);

		const result = runBash(
			[
				"--agent",
				"codex",
				"--workspace",
				workspace,
				"--output-dir",
				output,
				"--environment-dir",
				environment,
			],
			{
				cwd: fixture,
				env: {
					...wslSimulation,
					AI4S_CAPTURE: capture,
				},
			},
		);
		assert.equal(result.status, 37, result.stderr || result.stdout);
		const argv = readFileSync(capture, "utf8").trim().split("\n");
		assert.deepEqual(argv.slice(0, 3), ["run", "--project", root]);
		assert.equal(argv[3], "--locked");
		assert.match(argv.join("\n"), /molecular_modeling_environment\.py/);
		const summary = readFileSync(resolve(output, "setup-summary.md"), "utf8");
		assert.match(summary, /Status: \*\*failed\*\*/);
		assert.match(summary, /status 37/);
		assert.match(
			summary,
			new RegExp(root.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")),
		);
	} finally {
		rmSync(fixture, { recursive: true, force: true });
	}
});

test("WSL initializer refuses existing output without clobbering it", (t) => {
	const fixture = mkdtempSync(resolve(homedir(), ".ai4s-no-clobber-test-"));
	try {
		const bin = resolve(fixture, "bin");
		mkdirSync(bin);
		const wslSimulation = simulateSupportedWsl2(t, bin);
		if (!wslSimulation) return;
		const workspace = resolve(fixture, "workspace");
		const output = resolve(workspace, "existing-output");
		mkdirSync(output, { recursive: true });
		const marker = resolve(output, "setup-summary.md");
		writeFileSync(marker, "preserve me\n");
		const result = runBash(
			["--agent", "claude", "--workspace", workspace, "--output-dir", output],
			{ env: wslSimulation },
		);
		assert.equal(result.status, 2, result.stderr);
		assert.match(
			result.stderr,
			/Refusing to overwrite existing onboarding output/,
		);
		assert.equal(readFileSync(marker, "utf8"), "preserve me\n");
	} finally {
		rmSync(fixture, { recursive: true, force: true });
	}
});

test("WSL initializer refuses symbolic-link and junction targets without elevated Windows privileges", (t) => {
	const fixture = mkdtempSync(resolve(homedir(), ".ai4s-symlink-test-"));
	try {
		const bin = resolve(fixture, "bin");
		mkdirSync(bin);
		const wslSimulation = simulateSupportedWsl2(t, bin);
		if (!wslSimulation) return;
		const workspace = resolve(fixture, "workspace");
		const realOutput = resolve(workspace, "real-output");
		const linkedOutput = resolve(workspace, "linked-output");
		mkdirSync(realOutput, { recursive: true });
		symlinkSync(
			realOutput,
			linkedOutput,
			process.platform === "win32" ? "junction" : "dir",
		);
		const linkedResult = runBash(
			[
				"--agent",
				"codex",
				"--workspace",
				workspace,
				"--output-dir",
				linkedOutput,
			],
			{ env: wslSimulation },
		);
		assert.equal(linkedResult.status, 2, linkedResult.stderr);
		assert.match(
			linkedResult.stderr,
			/Refusing to overwrite existing onboarding output/,
		);

		const runOutput = resolve(workspace, "new-run-output");
		const existingEnvironment = resolve(workspace, "existing-environment");
		mkdirSync(existingEnvironment);
		const environmentResult = runBash(
			[
				"--agent",
				"claude",
				"--workspace",
				workspace,
				"--output-dir",
				runOutput,
				"--environment-dir",
				existingEnvironment,
			],
			{ env: wslSimulation },
		);
		assert.equal(environmentResult.status, 2, environmentResult.stderr);
		assert.match(
			environmentResult.stderr,
			/Refusing to overwrite existing environment diagnostics/,
		);
		const summary = readFileSync(
			resolve(runOutput, "setup-summary.md"),
			"utf8",
		);
		assert.match(summary, /Status: \*\*failed\*\*/);
		assert.match(summary, /existing environment diagnostics/);
	} finally {
		rmSync(fixture, { recursive: true, force: true });
	}
});

test("WSL initializer remains syntactically fail-closed", () => {
	const syntax = spawnSync("bash", ["-n", wslEntrypoint], { encoding: "utf8" });
	assert.equal(syntax.status, 0, syntax.stderr);
	const script = readFileSync(wslEntrypoint, "utf8");
	assert.match(script, /uv run --project "\$PLUGIN_ROOT" --locked/);
	assert.match(script, /molecular_modeling_environment\.py/);
	assert.match(script, /Codex CLI/);
	assert.match(script, /Claude Code/);
	assert.doesNotMatch(
		script,
		/^\s*(?:sudo\b|apt(?:-get)?\s+install\b|docker\s+pull\b|nvidia-ctk\b)/im,
	);
	assert.doesNotMatch(
		script,
		/curl[^\n|]*\|\s*(?:bash|sh)|wget[^\n|]*\|\s*(?:bash|sh)/i,
	);
	assert.doesNotMatch(script, /(?:codex|claude)\s+(?:login|auth)/i);
});

test("README keeps computation in WSL and documents the reviewed boundaries", () => {
	const readme = readFileSync(resolve(root, "README.md"), "utf8");
	assert.match(readme, /Start-AI4S-Workbench\.ps1/);
	assert.match(readme, /setup-wsl-workbench\.sh/);
	assert.match(readme, /Codex CLI/);
	assert.match(readme, /Claude Code/);
	assert.match(readme, /\/mnt\/c/);
	assert.match(readme, /environment_receipt\.json/);
	assert.match(readme, /Docker.*root|root.*Docker/i);
	assert.match(readme, /does not intentionally upload/i);
	assert.match(readme, /client\s+discovery/i);
	assert.doesNotMatch(
		readme,
		/curl[^\n|]*\|\s*(?:bash|sh)|Invoke-Expression|\biex\b/i,
	);
});
