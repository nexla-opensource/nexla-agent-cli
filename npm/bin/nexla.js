#!/usr/bin/env node
"use strict";
const path = require("path");
const { spawnSync } = require("child_process");

const binName = process.platform === "win32" ? "nexla-bin.exe" : "nexla-bin";
const bin = path.join(__dirname, binName);

const result = spawnSync(bin, process.argv.slice(2), { stdio: "inherit" });
if (result.error) {
  console.error(`nexla-cli: could not run bundled binary (${result.error.message})`);
  process.exit(1);
}
process.exit(result.status === null ? 1 : result.status);
