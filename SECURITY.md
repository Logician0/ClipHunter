# Security and public launch status

ClipHunter is currently a single-owner app listening on `127.0.0.1`. Do not publish this build to the internet as a multi-user service. The one shared password and SQLite library would give every signed-in visitor access to every project, video, and download. Processing would run on the owner's Mac; ordinary web visitors cannot lend their computer's CPU to server-side FFmpeg or Whisper jobs through a browser.

The public distribution uses a separate local installation for each person. Docker publishes only the web port to the local loopback address and keeps the API inside the private Compose network. Each installation has its own password and selected data folder. The public landing page and source ZIP contain no workspace database, media, cookies or `.env.docker`. Keep Docker Desktop's file sharing scoped to the chosen folder and do not change the loopback port mapping to `0.0.0.0`.

Implemented controls: loopback binding, a strict source-host allowlist, argument-array subprocess calls, password sessions on API and media routes, login rate limiting, size-limited request bodies, origin checking for mutations, HTTP security headers, and ignored secrets/media in Git. The Samsung drive must stay connected for the library to work.

The optional YouTube cookies import accepts a YouTube-only Netscape file under 300 KB, requires an authenticated session, and stores it on the Mac with owner-only permissions. This is a sensitive credential and should never be placed in Git, shared, or used in a public multi-user deployment. Delete `~/.config/ClipHunter/youtube-cookies.txt` to revoke ClipHunter's saved copy; also sign out of relevant Google sessions if the cookie file was exposed elsewhere.

Before a public multi-user launch, the app needs separate user identities, project ownership checks on every query and media response, per-user quotas and rate limits, a job scheduler with resource caps, CSRF protection, encrypted OAuth token storage, backup and restore, log rotation and monitoring, dependency scanning, and an independent security review. Put the public frontend behind an edge rate limiter and protect the origin. A Cloudflare Tunnel alone would expose the current shared workspace; Cloudflare Access could restrict access to one owner but would not make this a public multi-user product.

YouTube upload and scheduling require each user's Google OAuth authorization and a YouTube API project. Scheduled videos must be uploaded as private with a future `publishAt` time. No YouTube account connection or upload is active in this build.

This checklist is guided by [OWASP ASVS](https://asvs.owasp.org/), [Cloudflare's self-hosted application guidance](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/), and [YouTube's video API](https://developers.google.com/youtube/data/reference/rest/v3/videos). No application can guarantee that nobody will ever compromise it.
