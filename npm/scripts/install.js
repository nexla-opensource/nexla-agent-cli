"use strict";
// Downloads the prebuilt `nexla` binary matching this machine from the
// GitHub release tagged to match this package's version.
//
// Hardening (see issue #1, P0 #5):
//   - Downloads to a temp path, verifies SHA-256 against the release's
//     SHA256SUMS, chmods, then atomically renames into place.
//   - Rejects redirects to any non-https URL.
//   - Every failure path unlinks the temp file.
//   - Reuses a cached binary only after validating it (size + checksum,
//     or size + exec bit when no checksums are published).
//   - The ASSETS map below is the single source of truth for which
//     platforms are supported (package.json intentionally has no os/cpu).
const fs = require("fs");
const path = require("path");
const https = require("https");
const crypto = require("crypto");
const { URL } = require("url");

const ASSETS = {
  "darwin-arm64": "nexla-macos-arm64",
  "linux-x64": "nexla-linux-x64",
  "win32-x64": "nexla-windows-x64.exe",
};

const CHECKSUMS_ASSET = "SHA256SUMS";

// ---------------------------------------------------------------------------
// Pure helpers (exported for the self-check in install.test.js).
// ---------------------------------------------------------------------------

// Returns the release asset name for a platform/arch, or null if unsupported.
function assetFor(platform, arch) {
  return ASSETS[`${platform}-${arch}`] || null;
}

// A redirect Location is only allowed if it is an absolute https:// URL.
// Anything else (http:, file:, relative, garbage) is rejected.
function isAllowedRedirect(location) {
  if (!location || typeof location !== "string") return false;
  try {
    return new URL(location).protocol === "https:";
  } catch (_e) {
    return false;
  }
}

// Parse a `shasum -a 256`-style SHA256SUMS file and return the hex digest
// for `assetName`, or null if absent. Lines look like:
//   <64-hex>  <filename>
// (two spaces for binary mode, one for text; a leading "*" marks binary).
function expectedHashFor(checksumsText, assetName) {
  if (!checksumsText) return null;
  for (const rawLine of checksumsText.split("\n")) {
    const line = rawLine.trim();
    if (!line) continue;
    const m = line.match(/^([0-9a-fA-F]{64})\s+\*?(.+)$/);
    if (!m) continue;
    const [, hash, name] = m;
    // Match on basename so a "./dist/asset" path still resolves.
    if (name === assetName || path.basename(name) === assetName) {
      return hash.toLowerCase();
    }
  }
  return null;
}

// Compute the sha256 hex digest of a file's contents.
function sha256File(filePath) {
  const buf = fs.readFileSync(filePath);
  return crypto.createHash("sha256").update(buf).digest("hex");
}

// Decide whether an already-present binary can be reused.
//   - expectedHash present  -> file must exist, be non-empty, and match.
//   - expectedHash null      -> file must exist, be non-empty, and (on
//                               non-Windows) carry the owner-exec bit.
function isCachedBinaryValid(dest, expectedHash, platform, statImpl, hashImpl) {
  const stat = statImpl || fs.statSync;
  const hasher = hashImpl || sha256File;
  let st;
  try {
    st = stat(dest);
  } catch (_e) {
    return false;
  }
  if (!st || !st.size || st.size <= 0) return false;
  if (expectedHash) {
    let actual;
    try {
      actual = hasher(dest);
    } catch (_e) {
      return false;
    }
    return actual.toLowerCase() === expectedHash.toLowerCase();
  }
  // No checksum available: fall back to "non-empty + executable" on posix.
  if (platform === "win32") return true;
  // 0o100 == owner execute bit.
  return (st.mode & 0o100) !== 0;
}

// ---------------------------------------------------------------------------
// Network helpers (https-only, redirect-limited).
// ---------------------------------------------------------------------------

// Streams `url` into `destPath`. Rejects non-https redirects and unlinks
// the temp file on any failure.
function downloadToFile(url, destPath, redirectsLeft) {
  return new Promise((resolve, reject) => {
    const cleanup = () => {
      try {
        fs.unlinkSync(destPath);
      } catch (_e) {
        /* best-effort */
      }
    };
    https
      .get(url, (res) => {
        if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
          res.resume();
          if (redirectsLeft <= 0) return reject(new Error("too many redirects"));
          if (!isAllowedRedirect(res.headers.location)) {
            return reject(
              new Error(`refusing non-https redirect to ${res.headers.location}`)
            );
          }
          return resolve(downloadToFile(res.headers.location, destPath, redirectsLeft - 1));
        }
        if (res.statusCode !== 200) {
          res.resume();
          return reject(new Error(`download failed: HTTP ${res.statusCode} for ${url}`));
        }
        const file = fs.createWriteStream(destPath);
        res.pipe(file);
        file.on("finish", () => file.close((err) => (err ? reject(err) : resolve())));
        file.on("error", (err) => {
          cleanup();
          reject(err);
        });
        res.on("error", (err) => {
          cleanup();
          reject(err);
        });
      })
      .on("error", reject);
  });
}

// Fetches `url` as text. Resolves to null on 404 (used for the optional
// SHA256SUMS file). Rejects non-https redirects.
function fetchText(url, redirectsLeft) {
  return new Promise((resolve, reject) => {
    https
      .get(url, (res) => {
        if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
          res.resume();
          if (redirectsLeft <= 0) return reject(new Error("too many redirects"));
          if (!isAllowedRedirect(res.headers.location)) {
            return reject(
              new Error(`refusing non-https redirect to ${res.headers.location}`)
            );
          }
          return resolve(fetchText(res.headers.location, redirectsLeft - 1));
        }
        if (res.statusCode === 404) {
          res.resume();
          return resolve(null);
        }
        if (res.statusCode !== 200) {
          res.resume();
          return reject(new Error(`fetch failed: HTTP ${res.statusCode} for ${url}`));
        }
        let body = "";
        res.setEncoding("utf8");
        res.on("data", (chunk) => (body += chunk));
        res.on("end", () => resolve(body));
        res.on("error", reject);
      })
      .on("error", reject);
  });
}

// ---------------------------------------------------------------------------
// Install driver.
// ---------------------------------------------------------------------------

async function main() {
  const pkg = require("../package.json");
  const platform = process.platform;
  const arch = process.arch;
  const asset = assetFor(platform, arch);
  if (!asset) {
    console.error(
      `nexla-cli: no prebuilt binary for ${platform}-${arch}. ` +
        `Supported: ${Object.keys(ASSETS).join(", ")}`
    );
    process.exit(1);
  }

  const base = `https://github.com/nexla-opensource/nexla-agent-cli/releases/download/v${pkg.version}`;
  const assetUrl = `${base}/${asset}`;
  const checksumsUrl = `${base}/${CHECKSUMS_ASSET}`;
  const destName = platform === "win32" ? "nexla-bin.exe" : "nexla-bin";
  const dest = path.join(__dirname, "..", "bin", destName);
  const temp = `${dest}.download-${process.pid}`;

  // Fetch checksums first (may be absent on older releases -> graceful skip).
  let expectedHash = null;
  let checksumsAvailable = false;
  try {
    const checksumsText = await fetchText(checksumsUrl, 5);
    if (checksumsText) {
      checksumsAvailable = true;
      expectedHash = expectedHashFor(checksumsText, asset);
      if (!expectedHash) {
        console.error(
          `nexla-cli: ${CHECKSUMS_ASSET} present but has no entry for ${asset}`
        );
        process.exit(1);
      }
    }
  } catch (err) {
    console.error(
      `nexla-cli: failed to fetch ${CHECKSUMS_ASSET} from ${checksumsUrl}\n${err.message}`
    );
    process.exit(1);
  }
  if (!checksumsAvailable) {
    console.warn(
      "nexla-cli: checksum verification skipped (no checksums published for this release)"
    );
  }

  // Reuse a cached binary only if it validates.
  if (isCachedBinaryValid(dest, expectedHash, platform)) {
    console.log(`nexla-cli: using existing verified binary at ${dest}`);
    process.exit(0);
  }

  const cleanupTemp = () => {
    try {
      fs.unlinkSync(temp);
    } catch (_e) {
      /* best-effort */
    }
  };

  try {
    await downloadToFile(assetUrl, temp, 5);

    if (expectedHash) {
      const actual = sha256File(temp);
      if (actual.toLowerCase() !== expectedHash.toLowerCase()) {
        cleanupTemp();
        console.error(
          `nexla-cli: checksum mismatch for ${asset}\n` +
            `  expected ${expectedHash}\n  actual   ${actual}`
        );
        process.exit(1);
      }
    }

    if (platform !== "win32") fs.chmodSync(temp, 0o755);
    fs.renameSync(temp, dest);
    console.log(`nexla-cli: installed binary at ${dest}`);
  } catch (err) {
    cleanupTemp();
    console.error(`nexla-cli: failed to install binary from ${assetUrl}\n${err.message}`);
    process.exit(1);
  }
}

module.exports = {
  ASSETS,
  CHECKSUMS_ASSET,
  assetFor,
  isAllowedRedirect,
  expectedHashFor,
  sha256File,
  isCachedBinaryValid,
};

if (require.main === module) {
  main();
}
