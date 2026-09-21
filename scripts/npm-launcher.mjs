/** No-build npm commands for the existing Python application. */
import { spawn, spawnSync } from "node:child_process";
import { constants as fsConstants } from "node:fs";
import { access, copyFile } from "node:fs/promises";
import { constants as osConstants } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = fileURLToPath(new URL("../", import.meta.url));
const isWindows = process.platform === "win32";
const venvDirectory = path.join(projectRoot, ".venv");
const venvPython = path.join(venvDirectory, isWindows ? "Scripts" : "bin", isWindows ? "python.exe" : "python");
const pythonVersionCheck = "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)";

async function exists(filename) {
  try {
    await access(filename);
    return true;
  } catch (error) {
    if (error.code === "ENOENT") return false;
    throw error;
  }
}

function probe(command, args) {
  const result = spawnSync(command, args, {
    cwd: projectRoot,
    stdio: "ignore",
    windowsHide: true,
    shell: false,
    timeout: 15000,
  });
  return !result.error && result.status === 0;
}

function signalExitCode(signal) {
  return 128 + (osConstants.signals[signal] || 1);
}

/** Run an executable directly, keeping its output and shutdown behavior visible. */
function run(command, args, environment = process.env) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: projectRoot,
      stdio: "inherit",
      env: environment,
      windowsHide: true,
      shell: false,
    });
    const signals = isWindows ? ["SIGINT", "SIGTERM"] : ["SIGINT", "SIGTERM", "SIGHUP"];
    const forward = (signal) => {
      if (child.exitCode === null && child.signalCode === null) child.kill(signal);
    };
    const handlers = signals.map((signal) => {
      const handler = () => forward(signal);
      process.on(signal, handler);
      return [signal, handler];
    });
    const cleanup = () => handlers.forEach(([signal, handler]) => process.removeListener(signal, handler));
    child.once("error", (error) => {
      cleanup();
      reject(new Error(`Could not start ${path.basename(command)} (${error.code || error.message}).`));
    });
    child.once("close", (code, signal) => {
      cleanup();
      resolve(code ?? signalExitCode(signal));
    });
  });
}

async function requireSuccess(command, args, environment) {
  const code = await run(command, args, environment);
  if (code !== 0) {
    process.exitCode = code;
    throw new Error(`${path.basename(command)} exited with code ${code}. Setup stopped; see its output above.`);
  }
}

function findPython() {
  const candidates = isWindows
    ? [["py", ["-3.11"]], ["py", ["-3.12"]], ["python", []], ["python3", []], ["py", ["-3"]]]
    : [["python3", []], ["python", []]];
  for (const [command, args] of candidates) {
    if (probe(command, [...args, "-c", pythonVersionCheck])) return { command, args };
  }
  throw new Error("Python 3.11 or newer was not found. Install Python 3.11+ or uv, then run npm run setup again.");
}

async function setup() {
  const hasVenv = await exists(venvDirectory);
  if (hasVenv && (!await exists(venvPython) || !probe(venvPython, ["-c", pythonVersionCheck]))) {
    throw new Error("The existing .venv is not a working Python 3.11+ environment. Repair it before setup; this launcher will not delete it.");
  }

  if (probe("uv", ["--version"])) {
    console.log("Installing the frozen uv environment; existing extra tools are retained.");
    // Reuse an existing compatible interpreter instead of replacing its environment.
    await requireSuccess(
      "uv",
      ["sync", "--frozen", "--inexact", "--python", hasVenv ? venvPython : "3.11"],
      { ...process.env, UV_PROJECT_ENVIRONMENT: venvDirectory },
    );
  } else {
    if (!hasVenv) {
      const python = findPython();
      await requireSuccess(python.command, [...python.args, "-m", "venv", venvDirectory]);
    }
    console.log("Installing the hashed runtime requirements into .venv.");
    await requireSuccess(venvPython, ["-m", "pip", "install", "--require-hashes", "-r", path.join(projectRoot, "requirements-runtime.lock")]);
    await requireSuccess(venvPython, ["-m", "pip", "install", "--no-deps", "-e", projectRoot]);
  }

  try {
    await copyFile(path.join(projectRoot, ".env.example"), path.join(projectRoot, ".env"), fsConstants.COPYFILE_EXCL);
    console.log("Created .env from .env.example. Add your NEBIUS_API_KEY before using the model.");
  } catch (error) {
    if (error.code !== "EEXIST") throw error;
    console.log("Existing .env preserved.");
  }
  console.log("Setup complete. Run npm start, or npm start -- --port 8001.");
}

async function main() {
  if (Number(process.versions.node.split(".")[0]) < 20) throw new Error("This launcher requires Node.js 20 or newer.");
  const [command, ...args] = process.argv.slice(2);
  if (command === "setup") {
    if (args.length) throw new Error("npm run setup does not accept additional arguments.");
    await setup();
  } else if (command === "start") {
    if (!await exists(venvPython)) throw new Error("The project environment is missing. Run npm run setup first.");
    if (!probe(venvPython, ["-c", "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('crossword_agent') else 1)"])) {
      throw new Error("Crosscheck is not installed in the project environment. Run npm run setup first.");
    }
    process.exitCode = await run(venvPython, ["-m", "crossword_agent.cli", "serve", ...args]);
  } else {
    throw new Error("Use npm run setup or npm start [-- --port 8001].");
  }
}

main().catch((error) => {
  console.error(`Crosscheck: ${error.message}`);
  process.exitCode ||= 1;
});
