# Authentication

## Flow

```
LoginPage → LoginService → AuthManager → ApiClient.authenticate
                                      → TokenManager.store
                                      → SessionManager.mark_authenticated
```

## Tokens

`TokenManager` stores:

- access token
- optional refresh token
- optional `expires_at` (from `expires_in` when provided)

### Assumption

The current TDEI Gateway `/authenticate` endpoint returns an **access token**
(JWT). Refresh tokens may be absent. The client still implements
`/authenticate/refresh` for forward compatibility. If refresh is unavailable
and a 401 occurs, the user is returned to the login screen.

### Storage

Tokens are stored under QSettings with base64 obfuscation. This is **not**
OS keychain encryption. Mitigations:

- Never log tokens
- Never show tokens in UI
- Clear on logout / unauthorized
- Prefer short-lived server tokens

## Session UX

- Near expiry + refresh token → automatic refresh
- Refresh failure / 401 → “Your session has expired” + login
- QGIS itself is never force-closed
- **Toolbar / shortcut** (`plugin.run`): if not authenticated → open the sticky
  TDEI sign-in panel; if authenticated → open **map search**
- Map search, clip, OSW preview, and jobs require a session; they open the
  sign-in panel instead of proceeding when logged out
- A ZIP install on a new machine has **no** tokens — users must sign in once
  per environment (switching env in the status bar also signs out)

## Future SSO

If TDEI moves to browser OIDC, replace `LoginPage` credential fields with an
SSO action and keep `AuthManager` / `TokenManager` contracts stable.
