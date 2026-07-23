# AGENTS.md — Terminal Gravity CI Dead-Man

This public repository contains only a sanitized external availability monitor for Terminal Gravity self-hosted CI.

## Safety boundaries

- Never commit credentials, webhook URLs, hostnames, IP addresses, private repository contents, broker data, account data, or operational dashboards.
- GitHub Actions secrets are write-only runtime inputs and must never be printed.
- The external workflow may read and update only this repository's heartbeat issue and send a bounded Discord alert.
- The trusted heartbeat publisher may update only the heartbeat comment after the local self-hosted CI watchdog reports healthy.
- No IBKR, broker, order, sizing, Risk Gate, execution, deployment, Docker-socket, SSH, or performance-truth authority exists here.
- Do not add `pull_request_target` or expose secrets to pull-request workflows.

## Development

- Use short-lived branches and pull requests.
- Run `python3 -m unittest discover -s tests -v`, `python3 -m compileall -q scripts tests`, and `git diff --check` before merge.
- External monitoring runs only from the default branch on `schedule` or explicit `workflow_dispatch`.
- Pull requests run secret-free quality checks only.
