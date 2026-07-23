# Terminal Gravity CI Dead-Man

Public, sanitized dead-man monitoring for the Terminal Gravity self-hosted CI runner.

A trusted publisher updates one exact, identity-bound heartbeat comment only after a watchdog probe from the same invocation reports healthy with a matching cryptographic nonce attestation. A GitHub-hosted scheduled workflow, independent of the self-hosted machine, validates the exact heartbeat schema and alerts a bounded Discord webhook when the heartbeat is stale or malformed. It announces recovery when the heartbeat becomes healthy again. Alert deduplication state lives in one message owned by the same scoped webhook, so the workflow's GitHub token remains read-only.

## Boundaries

- No private source code or private GitHub metadata.
- No hostnames, IP addresses, remote access, or internal endpoints.
- No broker, IBKR, order, sizing, Risk Gate, execution, or performance-truth authority.
- No secrets in repository files, logs, comments, or heartbeat payloads.
- Pull-request workflows never receive the Discord webhook secret.
- The secret-bearing workflow cannot be dispatched against pull-request branches; manual checks use a default-branch-only repository-dispatch event.
- GitHub API and Discord webhook redirects are rejected.
- Malformed heartbeat or private deduplication state fails closed and alerts.

The public repository is intentional: standard GitHub-hosted Actions usage for public repositories does not consume private-repository hosted-runner minutes. The monitored private repository continues to execute its own tests on its isolated self-hosted runner.
