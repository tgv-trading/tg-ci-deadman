# Terminal Gravity CI Dead-Man

Public, sanitized dead-man monitoring for the Terminal Gravity self-hosted CI runner.

A trusted publisher updates one heartbeat comment only after the local runner watchdog reports healthy. A GitHub-hosted scheduled workflow, independent of the self-hosted machine, alerts a bounded Discord webhook when the heartbeat is stale and announces recovery. Alert deduplication state lives in one message owned by the same scoped webhook, so the workflow's GitHub token remains read-only.

## Boundaries

- No private source code or private GitHub metadata.
- No hostnames, IP addresses, remote access, or internal endpoints.
- No broker, IBKR, order, sizing, Risk Gate, execution, or performance-truth authority.
- No secrets in repository files, logs, comments, or heartbeat payloads.
- Pull-request workflows never receive the Discord webhook secret.

The public repository is intentional: standard GitHub-hosted Actions usage for public repositories does not consume private-repository hosted-runner minutes. The monitored private repository continues to execute its own tests on its isolated self-hosted runner.
