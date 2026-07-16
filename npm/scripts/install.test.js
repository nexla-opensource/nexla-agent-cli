"use strict";
// Dependency-free self-check for install.js's pure helpers.
// Run with: node scripts/install.test.js
const assert = require("assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const crypto = require("crypto");

const {
  ASSETS,
  assetFor,
  isAllowedRedirect,
  expectedHashFor,
  sha256File,
  isCachedBinaryValid,
} = require("./install.js");

let passed = 0;
function test(name, fn) {
  fn();
  passed += 1;
  console.log(`ok - ${name}`);
}

// --- ASSETS lookup: supported vs unsupported --------------------------------
test("assetFor resolves supported platforms", () => {
  assert.strictEqual(assetFor("darwin", "arm64"), "nexla-macos-arm64");
  assert.strictEqual(assetFor("linux", "x64"), "nexla-linux-x64");
  assert.strictEqual(assetFor("win32", "x64"), "nexla-windows-x64.exe");
});

test("assetFor returns null for unsupported platforms", () => {
  // Exactly the combos that the old os/cpu Cartesian product wrongly allowed.
  assert.strictEqual(assetFor("darwin", "x64"), null);
  assert.strictEqual(assetFor("linux", "arm64"), null);
  assert.strictEqual(assetFor("win32", "arm64"), null);
  assert.strictEqual(assetFor("sunos", "mips"), null);
  assert.strictEqual(Object.keys(ASSETS).length, 3);
});

// --- https-redirect rejection -----------------------------------------------
test("isAllowedRedirect accepts only absolute https URLs", () => {
  assert.strictEqual(isAllowedRedirect("https://example.com/a"), true);
  assert.strictEqual(isAllowedRedirect("http://example.com/a"), false);
  assert.strictEqual(isAllowedRedirect("ftp://example.com/a"), false);
  assert.strictEqual(isAllowedRedirect("file:///etc/passwd"), false);
  assert.strictEqual(isAllowedRedirect("/relative/path"), false);
  assert.strictEqual(isAllowedRedirect(""), false);
  assert.strictEqual(isAllowedRedirect(null), false);
});

// --- checksum parsing + mismatch --------------------------------------------
test("expectedHashFor parses SHA256SUMS and matches by name/basename", () => {
  const hashA = "a".repeat(64);
  const hashB = "b".repeat(64);
  const text = [
    `${hashA}  nexla-linux-x64`,
    `${hashB} *./dist/nexla-macos-arm64`, // binary marker + path
    "",
    "# a comment line that should be ignored",
  ].join("\n");
  assert.strictEqual(expectedHashFor(text, "nexla-linux-x64"), hashA);
  assert.strictEqual(expectedHashFor(text, "nexla-macos-arm64"), hashB);
  // Absent entry -> null (drives install.js's "no entry" hard-fail).
  assert.strictEqual(expectedHashFor(text, "nexla-windows-x64.exe"), null);
  // Empty/missing checksums -> null (drives graceful-degrade warn+proceed).
  assert.strictEqual(expectedHashFor("", "nexla-linux-x64"), null);
  assert.strictEqual(expectedHashFor(null, "nexla-linux-x64"), null);
});

// --- cached-binary validation -----------------------------------------------
test("cached-binary validation across checksum / exec-bit / size states", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "nexla-install-test-"));
  const bin = path.join(dir, "nexla-bin");
  fs.writeFileSync(bin, "fake-binary-contents");
  const realHash = sha256File(bin);
  const wrongHash = "c".repeat(64);

  // Checksum available + match -> valid.
  assert.strictEqual(isCachedBinaryValid(bin, realHash, "linux"), true);
  // Checksum available + mismatch -> invalid (re-download).
  assert.strictEqual(isCachedBinaryValid(bin, wrongHash, "linux"), false);

  // No checksum, posix: needs exec bit.
  fs.chmodSync(bin, 0o644);
  assert.strictEqual(isCachedBinaryValid(bin, null, "linux"), false);
  fs.chmodSync(bin, 0o755);
  assert.strictEqual(isCachedBinaryValid(bin, null, "linux"), true);

  // No checksum, windows: exec bit not required, non-empty is enough.
  assert.strictEqual(isCachedBinaryValid(bin, null, "win32"), true);

  // Empty file -> invalid regardless.
  const empty = path.join(dir, "empty-bin");
  fs.writeFileSync(empty, "");
  assert.strictEqual(isCachedBinaryValid(empty, null, "linux"), false);
  assert.strictEqual(isCachedBinaryValid(empty, realHash, "linux"), false);

  // Missing file -> invalid.
  assert.strictEqual(
    isCachedBinaryValid(path.join(dir, "nope"), null, "linux"),
    false
  );

  fs.rmSync(dir, { recursive: true, force: true });
});

// --- sha256File sanity ------------------------------------------------------
test("sha256File matches crypto over the same bytes", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "nexla-install-test-"));
  const f = path.join(dir, "f");
  const data = "hello-nexla";
  fs.writeFileSync(f, data);
  const expected = crypto.createHash("sha256").update(data).digest("hex");
  assert.strictEqual(sha256File(f), expected);
  fs.rmSync(dir, { recursive: true, force: true });
});

console.log(`\n${passed} checks passed`);
