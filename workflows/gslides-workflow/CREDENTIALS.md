# Credentials you must supply — gslides-workflow

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
├── client_secret.<alias>.json   # you download this from Google Cloud
└── token.<alias>.json           # created automatically on first auth
```

`<alias>` is the `--account` value (`work`, `personal`, or anything you like).
Use `client_secret.json` / `token.json` for the `default` alias.

## How to obtain `client_secret.<alias>.json`

1. Open the [Google Cloud console](https://console.cloud.google.com/) and
   create (or pick) a project.
2. Enable the **Google Slides API + Google Drive API + Google Sheets API** for that project.
3. **APIs & Services → OAuth consent screen**: configure it, and add your own
   Google account as a **Test user** while the app is in *Testing*.
4. **APIs & Services → Credentials → Create credentials → OAuth client ID**,
   application type **Desktop app**.
5. Download the JSON and save it as
   `~/.agents/credentials/client_secret.<alias>.json`.

Required scopes: `presentations`, `drive`, `drive.file`, `spreadsheets`.

## First run

```bash
python google-auth-workflow/cli.py slides --account <alias>
```

A browser opens for consent; on success `token.<alias>.json` is written next to
the client secret. Both files are secrets: they grant access to your account.
Keep them out of version control (they live outside the repository, and
`.gitignore` excludes `credentials/` regardless) and revoke them at
<https://myaccount.google.com/permissions> when you are done.

## Optional: pin an account to an alias

`google_auth_profiles.py` ships with empty `expected_email` / `login_hint`
values in `NAMED_ACCOUNTS`. Fill in your own address to have the auth flow
assert the token belongs to that account and to pre-select it on the consent
screen. Leaving them empty disables both behaviours.
