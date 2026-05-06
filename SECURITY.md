# Security

Matriosha is a Python CLI for encrypted agent memory with verifiable integrity.

## Local mode threat model

Local mode protects encrypted vault files at rest.

It is designed to protect against:
- stolen encrypted vault files,
- accidental disclosure of encrypted memory blobs,
- offline inspection of encrypted local storage,
- integrity tampering detectable through hash and Merkle verification.

Local mode assumes the local operating system, shell, Python runtime, and installed dependencies are trusted.

Local mode does not protect against:
- malware running as the same user,
- compromised shell startup files,
- malicious Python packages,
- keyloggers,
- debuggers or process-memory inspection,
- modified local Matriosha source code or binaries,
- AI coding agents or automation tools with access to local files, environment variables, terminal output, or debug logs.

If an attacker controls the local machine or runtime, they may be able to capture passphrases or decrypted material.

## Passphrase handling

For normal local use, prefer the interactive hidden passphrase prompt.

`MATRIOSHA_PASSPHRASE` is intended for automation and non-interactive use. It is less safe than an interactive prompt because environment variables can be exposed to local processes, shell configuration, logs, crash reports, debug tooling, or AI coding agents running in the same environment.

Avoid putting vault passphrases in:
- shell history,
- `.env` files,
- committed config files,
- shared terminals,
- CI logs,
- screenshots,
- prompts given to AI coding agents.

## Managed mode

Managed mode automates key custody after authentication. Managed users should not run `vault init` or manage local vault passphrases for managed key custody.

Managed mode still assumes that the local CLI runtime and authenticated user session are not compromised.

## Reporting security issues

If you believe you found a security issue, please report it privately to support@matriosha.in instead of opening a public issue with exploit details.
