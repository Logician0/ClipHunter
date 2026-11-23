# Connect a YouTube channel and publish a clip

ClipHunter uploads through the official YouTube Data API. This local edition runs on your computer. Each local installation keeps its own Google authorization files under `~/.config/ClipHunter/` with owner-only permissions; those files are excluded from the public repository and from the Samsung media folder.

## One-time Google Cloud setup

1. Open [Google Cloud Console](https://console.cloud.google.com/), select or create a project, and enable **YouTube Data API v3**.
2. Configure the OAuth consent screen for that project. Add your Google account as a test user if the app is in testing. To let people outside your test list connect to a shared OAuth app, complete Google's required publishing and verification steps.
3. Under **APIs & Services → Credentials**, create an **OAuth client ID** with application type **Desktop app**. Download its JSON file. Keep this file private.
4. In local ClipHunter, open **Settings → YouTube channel** and import that JSON. Choose **Connect a YouTube channel**. Google will ask you to choose a Google account/channel and approve upload and channel-read access. Confirm that the channel name shown in ClipHunter is the one you intend to use.

A local user can instead create a separate Google Cloud OAuth client and import its own JSON. The public ClipHunter landing page is static; it cannot connect to a visitor's channel until that visitor runs a local ClipHunter installation or a future hosted account service.

## Publish or schedule

1. Finish and export a clip in the editor at 1080×1920. If you want captions burned into the video, turn them on and verify them **before** export.
2. In **YouTube upload**, review the destination channel, suggested title, description and tags. Edit them as needed.
3. Choose **Private now**, **Unlisted now**, **Public now**, or **Schedule public release**. For a schedule, choose a future local date and time. YouTube receives the video as private with `publishAt` set to that time.
4. Answer **Is this video made for kids?** and choose the upload button. The progress bar shows bytes sent, percentage and ETA. A failed transfer can be retried without starting a new upload session when YouTube still has the resumable session.
5. When ClipHunter shows a YouTube link, open it to check processing and visibility on YouTube. YouTube may take additional time to process the uploaded video.

Disconnecting a channel revokes its token and removes the local copy. An upload already in progress must finish first. Google may limit uploads, request app verification, or reject a video; ClipHunter shows the API error without treating the upload as successful.

References: [Google OAuth desktop flow](https://developers.google.com/identity/protocols/oauth2/resources/loopback-migration), [YouTube videos.insert](https://developers.google.com/youtube/data/reference/rest/v3/videos/insert), [resumable uploads](https://developers.google.com/youtube/data/guides/using_resumable_upload_protocol), [scheduled publication](https://developers.google.com/youtube/data/reference/rest/v3/videos#status.publishAt).
