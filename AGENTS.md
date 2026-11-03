# Instructions for AI agents

You are an AI coding agent (Claude Code, Codex, Cursor...) and your user asked you to install or use **simplelogin-cli**. This file tells you how. Keep the safety rules at the end: they matter more than the rest.

## What it does

`simplelogin` drives a [SimpleLogin](https://simplelogin.io) account (email aliases) through its API: list, create, enable, disable, edit and delete aliases, manage mailboxes and custom domains, change account settings, export aliases as CSV. It needs Python 3.9+ and `curl`, no other dependency. macOS only: the API key lives in the macOS Keychain (service `simplelogin-cli.api`).

## Install

Run, then read the output: every line starts with `✓`, `!` (warning) or `✗` (blocking).

```sh
curl -fsSL https://raw.githubusercontent.com/pyxl-dev/simplelogin-cli/main/install.sh | sh
```

- `✗ python3 is missing` or `Python 3.9 or newer is needed`: tell the user. Do not install system tools without asking.
- `! ... is not on your PATH`: give the user the `export` line printed, do not edit their shell files without asking.
- Check: `simplelogin --help` prints the usage.

The API key is created by the user in SimpleLogin (Settings, API Keys). They run `simplelogin configure` themselves and paste the key in the hidden prompt. Do not ask for the key in chat and do not run `configure` for them. `simplelogin whoami` then checks access.

## Use

```sh
simplelogin alias list [search] [--enabled|--disabled|--pinned] [--json]
simplelogin alias show <address|id>
simplelogin alias new <prefix> [--domain D] [--mailbox M ...] [--note N] [--name N] [--hostname H]
simplelogin alias random [--note N] [--mode word|uuid] [--hostname H]
simplelogin alias enable|disable|activity|contacts <address|id>
simplelogin alias edit <address|id> [--note N] [--name N] [--mailbox M ...] [--pin|--unpin]
simplelogin alias reply <address|id> <contact-email>
simplelogin alias delete <address|id> --yes-destructive
simplelogin mailbox list | add <email> | default <mailbox> | delete <mailbox> [--transfer-to M] --yes-destructive
simplelogin domain list | set <domain> [--catch-all on|off] [--random-prefix on|off] [--name N] [--mailbox M ...] | trash <domain>
simplelogin domain dns <domain> [--zone Z] [--verification "sl-verification=..."] [--format o2switch|table]
simplelogin setting show | set key=value ...
simplelogin export > aliases.csv
```

- Alias references are the full address or the numeric id.
- `domain dns` only prints DNS records (as `o2switch dns set` commands or as a tab-separated table, `$SIMPLELOGIN_DNS_FORMAT` sets the default). It changes nothing by itself. Adding a custom domain is only possible in the SimpleLogin web interface.
- Tests: `python3 -m unittest discover -s tests -v` (no network, no key).

## Safety rules

- Never ask the user to paste the API key in chat. Never pass it as an argument or write it in a file: it stays in the Keychain.
- Creating, editing, enabling and disabling an alias is reversible and fine to run. Deleting an alias or a mailbox is not: only add `--yes-destructive` after the user explicitly agreed to that exact deletion. To stop an alias receiving mail, use `alias disable`.
- Deleting a mailbox without `--transfer-to` also deletes its aliases. Say so before asking.
- `setting set` changes the whole account behaviour: show the user the `key=value` pairs first.
- Do not run write commands against a real account just to test the tool: use `--help` and read-only commands (`list`, `show`, `whoami`).
