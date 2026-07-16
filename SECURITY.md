# Security Policy

## Supported versions

Security fixes are released against the latest published version of
`nexla-cli`. Please upgrade to the newest release before reporting an issue.

| Version | Supported |
| ------- | --------- |
| 0.3.x   | Yes       |
| < 0.3   | No        |

## Reporting a vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Report vulnerabilities privately so we can fix them before details become
public. Choose either channel:

- Email **security@nexla.com** <!-- placeholder: confirm the correct Nexla security intake address before publishing -->
- Or use GitHub's private
  ["Report a vulnerability"](https://github.com/nexla-opensource/nexla-agent-cli/security/advisories/new)
  advisory form.

Please include:

- The version of `nexla-cli` affected.
- A description of the issue and its impact.
- Steps to reproduce, or a proof of concept, where possible.

We aim to acknowledge reports within a few business days and will keep you
informed as we work on a fix. Please give us a reasonable window to release
a patch before any public disclosure.

## Why this matters for this project

`nexla-cli` has a security surface worth reporting against:

- **Native binaries.** Releases distribute prebuilt native binaries (via npm
  and GitHub Releases). Report anything that could compromise the build,
  signing, or distribution of these artifacts.
- **Bearer tokens.** The CLI reads a Nexla API bearer token from the
  `NEXLA_TOKEN` environment variable and sends it to the Nexla API. Report any
  path that could leak this token (for example through logs, error output, or
  crash dumps) or otherwise expose it to untrusted parties.
