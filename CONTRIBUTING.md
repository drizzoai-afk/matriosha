# Contributing to Matriosha

Thank you for your interest in contributing to Matriosha.

Matriosha is an open-source project released under the BSD 3-Clause License. By contributing to this repository, you agree that your contributions will be licensed under the same license.

## Ways to contribute

You can help by:

- Reporting bugs
- Suggesting improvements
- Improving documentation
- Adding tests
- Fixing issues
- Improving developer experience

## Before opening an issue

Before opening a new issue, please:

1. Search existing issues to avoid duplicates.
2. Include the Matriosha version you are using.
3. Include your operating system and Python version.
4. Include the exact command you ran.
5. Include the full error output, with secrets redacted.

Please never include API keys, tokens, passwords, private keys, .env files, database dumps, or other sensitive data in issues or pull requests.

## Development setup

Clone the repository:

    git clone https://github.com/drizzoai-afk/matriosha.git
    cd matriosha

Create and activate a virtual environment:

    python3 -m venv .venv
    source .venv/bin/activate

Install the project in editable mode with development tools:

    python3 -m pip install --upgrade pip
    python3 -m pip install -e ".[dev]"

If your environment does not use the optional development extra, install the needed tools directly:

    python3 -m pip install pytest ruff build twine

## Code style

Matriosha uses Ruff for formatting.

Check formatting:

    ruff format --check .

Apply formatting:

    ruff format .

## Tests

Run the test suite with:

    python3 -m pytest

Before opening a pull request, please make sure:

    ruff format --check .
    python3 -m pytest

both pass.

## Pull request guidelines

Please keep pull requests focused and easy to review.

A good pull request should:

- Explain what changed and why
- Include tests for behavior changes
- Update documentation when user-facing behavior changes
- Avoid unrelated formatting or refactoring
- Avoid committing generated files, local environments, caches, logs, or secrets

## Security reports

Please do not report security vulnerabilities in public issues.

If you believe you have found a security issue, open a private security advisory on GitHub if available, or contact the project maintainer privately through the repository owner profile.

When reporting a security issue, include:

- A clear description of the vulnerability
- Steps to reproduce
- Potential impact
- Any suggested mitigation

Please do not include real secrets, production data, or third-party confidential information.

## License

By contributing, you agree that your contribution is licensed under the BSD 3-Clause License used by this project.
