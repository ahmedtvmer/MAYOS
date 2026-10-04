# Cloudflare Pages setup (issue #129)

One-time, owner-only setup of the free web host for the closed trial (ADR 048).
The web app is served from `<project>.pages.dev`, separate from the Fly API
(`https://mayos-api.fly.dev`). Deploying builds to it is #130; this page only
creates the host, the credentials the deploy uses, and the origin allow-lists.

Nothing here goes in the repository: the API token and account ID live in your
shell or password manager.

## 1. Account

1. Sign in or sign up at <https://dash.cloudflare.com>. The free plan is enough.
2. Note the **Account ID**: open **Workers & Pages**; it is shown in the right
   sidebar ("Account details"). It is also the hex segment after
   `dash.cloudflare.com/` in the address bar.

## 2. API token (Cloudflare Pages: Edit, this account only)

1. Top-right avatar → **My Profile** → **API Tokens** → **Create Token**.
2. Choose **Create Custom Token** → **Get started**.
3. Name: `mayos-pages-deploy`.
4. **Permissions:** `Account` · `Cloudflare Pages` · `Edit`. Add nothing else.
5. **Account Resources:** `Include` · your account (not "All accounts").
6. Leave Client IP filtering empty, optionally set a TTL, then
   **Continue to summary** → **Create Token**. Copy it now; it is shown once.
7. Keep it locally in `~/.config/mayos/web.env` (mode 600), the file
   `scripts/deploy_web.sh` sources, together with the other web build inputs:

   ```bash
   mkdir -p ~/.config/mayos && touch ~/.config/mayos/web.env && chmod 600 ~/.config/mayos/web.env
   # ~/.config/mayos/web.env
   CLOUDFLARE_API_TOKEN="<token>"
   CLOUDFLARE_ACCOUNT_ID="<account id>"
   GOOGLE_WEB_CLIENT_ID="<web-client-id>.apps.googleusercontent.com"
   POSTHOG_CLIENT_KEY="phc_<public-project-key>"
   ```

   Never paste it into `.env`, `fly.toml`, an issue, or a commit.

## 3. Pages project (direct upload, no Git integration)

The CLI route is exact and needs only Node (`npx` fetches wrangler):

```bash
set -a; source ~/.config/mayos/web.env; set +a
npx wrangler pages project create mayos --production-branch=main
# If the name is taken in your account, use the fallback:
# npx wrangler pages project create mayos-app --production-branch=main
```

Dashboard alternative: **Workers & Pages** → **Create** → **Pages** tab →
**Upload assets** (direct upload, not "Connect to Git") → project name `mayos`
→ **Create project**. The dashboard asks for a first upload; drop any folder
holding a one-line `index.html` placeholder. #130's deploy replaces it.

**Record the real origin.** Open the project in the dashboard and read the
`*.pages.dev` link on its page. Cloudflare adds a random suffix when the
`pages.dev` subdomain is already taken globally (e.g. `mayos-7xq.pages.dev`), so
the origin may not equal `https://<project name>.pages.dev`. Use exactly what the
dashboard shows, with `https://` and no trailing slash, in every step below.
Preview deployments (`<hash>.<project>.pages.dev`) are deliberately not added
to any allow-list.

## 4. Fly: allow the Pages origin (CORS)

The API allows browser origins from `UI_BASE_URL`, a comma-separated list
(`svc/app.py` `web_origins()`). It is not a secret, so set it in `fly.toml`:

```toml
[env]
  UI_BASE_URL = "https://mayos.pages.dev"
```

then `fly deploy`. (`fly.toml` already carries `https://mayos.pages.dev`, the origin of the project created for #129; change it if yours differs.) (`fly secrets set UI_BASE_URL="https://mayos.pages.dev"`
also works and restarts the Machine, but keep it in one place only: a secret
overrides `[env]`.)

Check it from any terminal; the response must echo the Pages origin:

```bash
curl -si -X OPTIONS https://mayos-api.fly.dev/healthz \
  -H "Origin: https://mayos.pages.dev" \
  -H "Access-Control-Request-Method: GET" | grep -i access-control-allow-origin
# access-control-allow-origin: https://mayos.pages.dev
```

## 5. Google Cloud (#112): swap `mayos.app` for the Pages origin

In the project that owns the web OAuth client:

1. **Google Auth Platform → Clients** (or **APIs & Services → Credentials**) →
   the *Web application* client → **Authorized JavaScript origins**: remove
   `https://mayos.app`, add the Pages origin, **Save**.
2. **Google Auth Platform → Branding** → **Authorized domains**: remove
   `mayos.app`, add the Pages host without scheme (e.g. `mayos.pages.dev`;
   `pages.dev` is a public suffix, so the project host is the registrable
   domain), **Save**.

Origin changes can take a few minutes to reach sign-in.

## 6. Close the loop

Comment the final origin on #129 (e.g. "Pages origin: https://mayos.pages.dev")
and tick the checklist. #130 reads it for the deploy script, headers and CSP.
