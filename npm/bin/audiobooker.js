#!/usr/bin/env node
"use strict";

// ---------------------------------------------------------------------------
// @mcptoolshop/audiobooker — npm launcher
//
// audiobooker is a pure-Python CLI (PyPI: audiobooker-ai). This thin wrapper
// bootstraps a managed virtualenv on first run, pip-installs the pinned version
// from PyPI, and execs the real `audiobooker` entry point with full arg/stdio
// passthrough. No binary download, no system Python pollution.
//
// Core is installed by default (parse / cast / compile / review — fast).
// Audio rendering needs the heavy voice-soundboard TTS engine; opt in with:
//   AUDIOBOOKER_INSTALL_EXTRAS=render npx @mcptoolshop/audiobooker render ...
// (then ffmpeg must also be on PATH for M4B assembly).
// ---------------------------------------------------------------------------

const { spawnSync } = require("child_process");
const path = require("path");
const fs = require("fs");
const os = require("os");

const TOOL = "audiobooker";          // CLI entry name inside the venv
const PKG = "audiobooker-ai";        // PyPI distribution name
const VERSION = "2.1.1";             // pinned PyPI version (kept in lockstep with the package)
const IS_WIN = process.platform === "win32";

// XDG / LOCALAPPDATA-compliant install root, overridable for testing.
const dataHome = IS_WIN
  ? (process.env.LOCALAPPDATA || path.join(os.homedir(), "AppData", "Local"))
  : (process.env.XDG_DATA_HOME || path.join(os.homedir(), ".local", "share"));
const installRoot = process.env.AUDIOBOOKER_BOOTSTRAP_ROOT || path.join(dataHome, TOOL);
const venvDir = path.join(installRoot, "venv");
const metaPath = path.join(installRoot, "install.json");
const venvBin = IS_WIN
  ? path.join(venvDir, "Scripts", `${TOOL}.exe`)
  : path.join(venvDir, "bin", TOOL);
const venvPython = IS_WIN
  ? path.join(venvDir, "Scripts", "python.exe")
  : path.join(venvDir, "bin", "python3");

const extras = (process.env.AUDIOBOOKER_INSTALL_EXTRAS || "").trim(); // e.g. "render"
const installSpec = extras ? `${PKG}[${extras}]==${VERSION}` : `${PKG}==${VERSION}`;

function findPython() {
  // Windows: prefer the py launcher, then python. POSIX: python3, then python.
  const candidates = IS_WIN ? ["py", "python", "python3"] : ["python3", "python"];
  for (const cmd of candidates) {
    const args = cmd === "py" ? ["-3", "--version"] : ["--version"];
    const r = spawnSync(cmd, args, { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
    if (r.status === 0) {
      const ver = (r.stdout || r.stderr || "").trim();
      const m = ver.match(/Python\s+(\d+)\.(\d+)/);
      if (m && parseInt(m[1], 10) >= 3 && parseInt(m[2], 10) >= 10) {
        return cmd === "py" ? { cmd: "py", pre: ["-3"] } : { cmd, pre: [] };
      }
    }
  }
  return null;
}

function readMeta() {
  try {
    return JSON.parse(fs.readFileSync(metaPath, "utf8"));
  } catch {
    return null;
  }
}

function writeMeta(obj) {
  fs.mkdirSync(installRoot, { recursive: true });
  fs.writeFileSync(metaPath, JSON.stringify(obj, null, 2) + "\n");
}

function fail(message, hint) {
  process.stderr.write(`\n${TOOL}: ${message}\n`);
  if (hint) process.stderr.write(`\n${hint}\n`);
  process.stderr.write("\n");
  process.exit(1);
}

function bootstrap() {
  const forceReinstall = process.env.AUDIOBOOKER_FORCE_REINSTALL === "1";
  const meta = readMeta();
  const versionMatch = meta && meta.version === VERSION && meta.extras === extras;
  const binaryPresent = fs.existsSync(venvBin);

  // Fast path — venv exists, version + extras match, no forced reinstall.
  if (versionMatch && binaryPresent && !forceReinstall) return;

  // Tell the user which of the five states we're in.
  if (forceReinstall) {
    process.stderr.write(`Forced reinstall requested (AUDIOBOOKER_FORCE_REINSTALL=1).\n`);
  } else if (meta && meta.version !== VERSION) {
    process.stderr.write(`Updating ${TOOL}: ${meta.version} -> ${VERSION}\n`);
  } else if (meta && meta.extras !== extras) {
    process.stderr.write(`Reconfiguring ${TOOL} (extras: "${meta.extras || "none"}" -> "${extras || "none"}")...\n`);
  } else if (meta && !binaryPresent) {
    process.stderr.write(`Repairing ${TOOL}: entry point missing, reinstalling ${VERSION}...\n`);
  } else {
    process.stderr.write(`First run: setting up ${TOOL} ${VERSION}${extras ? ` [${extras}]` : ""}...\n`);
  }

  const py = findPython();
  if (!py) {
    fail(
      "Python 3.10+ is required but was not found.",
      "Install Python 3.10 or newer and try again:\n" +
      "  Windows:        winget install Python.Python.3.12   (or https://python.org)\n" +
      "  macOS:          brew install python\n" +
      "  Ubuntu/Debian:  sudo apt install python3 python3-venv"
    );
  }

  // Force-reinstall nukes a corrupted venv.
  if (forceReinstall && fs.existsSync(venvDir)) {
    process.stderr.write("Removing existing environment...\n");
    fs.rmSync(venvDir, { recursive: true, force: true });
  }

  if (!fs.existsSync(venvPython)) {
    fs.mkdirSync(installRoot, { recursive: true });
    const r = spawnSync(py.cmd, [...py.pre, "-m", "venv", venvDir], { stdio: "inherit" });
    if (r.status !== 0) {
      fail(
        "Failed to create a Python virtual environment.",
        "The venv module may be missing. Try:\n" +
        "  Ubuntu/Debian:  sudo apt install python3-venv\n" +
        "  Fedora/RHEL:    sudo dnf install python3-libs"
      );
    }
  }

  // pip install the pinned version (+ extras). --force-reinstall when repairing
  // so pip recreates the entry-point script even if metadata looks current.
  const needsForce = !binaryPresent || forceReinstall;
  const pipArgs = ["-m", "pip", "install", "--quiet", "--upgrade"];
  if (needsForce) pipArgs.push("--force-reinstall");
  pipArgs.push(installSpec);
  process.stderr.write(`Installing ${installSpec}...\n`);
  const pip = spawnSync(venvPython, pipArgs, { stdio: "inherit" });
  if (pip.status !== 0) {
    fail(
      `pip install failed (exit ${pip.status}).`,
      "Check your network connection and try again, or install manually:\n" +
      `  pip install ${installSpec}`
    );
  }

  if (!fs.existsSync(venvBin)) {
    fail(
      `Installation completed but the ${TOOL} entry point was not found.`,
      `Expected: ${venvBin}\n` +
      "Try a forced reinstall:\n" +
      `  AUDIOBOOKER_FORCE_REINSTALL=1 npx @mcptoolshop/${TOOL} --help`
    );
  }

  writeMeta({ version: VERSION, extras, installedAt: new Date().toISOString(), python: py.cmd });
  process.stderr.write("Ready.\n");
}

bootstrap();
const result = spawnSync(venvBin, process.argv.slice(2), { stdio: "inherit" });
if (result.error) {
  fail(`Failed to execute ${TOOL}: ${result.error.message}`);
}
process.exit(result.status === null ? 1 : result.status);
