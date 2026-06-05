# NodeSeek API Sign-in

Python script for signing in to NodeSeek with cookie-based account configuration.

## Usage

Install dependencies:

```powershell
poetry install
```

Run the sign-in script:

```powershell
poetry run python -m nodeseek_signin
```

## Environment

- `NS_COOKIE`: required. Use `&` to separate multiple account cookies.
- `NS_RANDOM`: optional. Set to `true` to use random sign-in mode.
- `ENABLE_STATISTICS`: optional. Set to `false` to skip statistics lookup.
- `COOKIE_WRITEBACK`: optional. Defaults to enabled in GitHub Actions and disabled locally.
- `PROXY_URL`: optional HTTP/HTTPS proxy URL.
- `TIMEOUT`: optional request timeout in seconds.

## GitHub Actions Secrets

- `NS_COOKIE`: NodeSeek cookie string.
- `NS_COOKIE_WRITE_TOKEN`: PAT used only to update `NS_COOKIE` when NodeSeek refreshes cookies.

The PAT must be able to write Actions secrets for this repository. Use a fine-grained PAT
scoped to this repository with repository secrets write access, or a classic PAT with the
minimum repository access your account allows.
