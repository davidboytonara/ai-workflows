# Credentials you must supply — gmail-workflow

**Nothing in this repository contains credentials.** This workflow will not run
until you supply your own OAuth files.

They live in ONE directory shared by the gsheet, gdocs, gslides and gmail
workflows, set by `GOOGLE_CREDENTIALS_DIR` in `~/.agents/.env` and defaulting
to `~/.agents/credentials/`. It sits outside this repository, so it can never
be committed by accident:

```bash
mkdir -p ~/.agents/credentials && chmod 700 ~/.agents/credentials
```

```
~/.agents/credentials/
├── client_secret.<alias>.json    # you download this from Google Cloud
├── token.<alias>.json            # created automatically on first auth
└── token.calendar.<alias>.json   # only if you use the calendar lookups
```

`<alias>` is the `--account` value (`work`, `personal`, or anything you like).
Use `client_secret.json` / `token.json` for the `default` alias.

## How to obtain `client_secret.<alias>.json`

1. Open the [Google Cloud console](https://console.cloud.google.com/) and
   create (or pick) a project.
2. Enable the **Gmail API** (and the **Google Calendar API** if you want the
   calendar-aware features).
3. **APIs & Services → OAuth consent screen**: configure it, and add your own
   Google account as a **Test user** while the app is in *Testing*.
4. **APIs & Services → Credentials → Create credentials → OAuth client ID**,
   application type **Desktop app**.
5. Download the JSON and save it as
   `~/.agents/credentials/client_secret.<alias>.json`.

Required scopes: `gmail.readonly`, `gmail.compose`, `gmail.modify` (plus
`calendar.readonly` for the calendar token).

## First run

```bash
python gmail-workflow/cli.py auth --account <alias>
```

A browser opens for consent; on success `token.<alias>.json` is written next to
the client secret. Both files are secrets: they grant read, compose and modify
access to your mailbox. Keep them out of version control (they live outside the repository, and
`.gitignore` excludes `credentials/` regardless) and revoke them at
<https://myaccount.google.com/permissions> when you are done.

## Optional: pin an account to an alias

`google_auth_profiles.py` ships with empty `expected_email` / `login_hint`
values in `NAMED_ACCOUNTS`. Fill in your own address to have the auth flow
assert the token belongs to that account and to pre-select it on the consent
screen. Leaving them empty disables both behaviours.

## Optional: your own addresses

`scripts/check_resolution.py` ships with an empty `DEFAULT_OWN_ADDRESSES`
tuple. Pass `--own-address you@example.com` (repeatable), or fill the tuple in
locally, so the script can tell your outbound mail from inbound mail.
