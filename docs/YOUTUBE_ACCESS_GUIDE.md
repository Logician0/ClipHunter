# YouTube access and cookie guide

## Your current situation

ClipHunter already imported your `cookies.txt` file. A format check on 21 November found video and audio formats for your failed link after I installed yt-dlp's missing EJS component. You do **not** need to import the same file again now. **Saved** means only that the file was stored; it does not start or resume a project. Open your project and choose **Retry scan**. Its status should change to **scanning**. I have already pressed Retry for the current project; watch its status before pressing it again.

## When you need to make a new cookies file

1. Open a new **Incognito** window in Chrome. Sign in to YouTube there and complete any human check.
2. In that same tab, open `https://www.youtube.com/robots.txt`. Keep it as the only Incognito tab.
3. Using a trusted browser extension that exports **Netscape-format** cookies, export cookies for **youtube.com only** to a file named `cookies.txt`. The yt-dlp FAQ lists **Get cookies.txt LOCALLY** for Chrome; avoid similarly named extensions. Do not export cookies for all websites.
4. Close the Incognito window. Treat `cookies.txt` like a password. Do not attach it to chat, email it, or put it in GitHub.
5. In ClipHunter, open **Settings → YouTube access**. Select the exported `cookies.txt`. Wait for **YouTube session imported**.
6. Return to the failed project and click **Retry scan** once. The scan can take several minutes. **Saved** by itself is not a scan result.

The file should begin with `# Netscape HTTP Cookie File` or `# HTTP Cookie File`. ClipHunter accepts YouTube-related cookies under 300 KB and stores the imported copy only on this Mac at `~/.config/ClipHunter/youtube-cookies.txt` with owner-only permissions. It does not store the imported credential on the Samsung media drive. Delete the downloaded export from Downloads once you have confirmed ClipHunter imported it; the imported copy remains until you replace or delete it.

If a fresh import still fails, check the project error message. YouTube can expire cookies, block automated access, or change its video formats. A stream that has ended should be retried as a VOD. ClipHunter processes one hour at a time. The browser check alone cannot authenticate yt-dlp; the cookie import bridges that gap.

Sources: [yt-dlp YouTube cookie guidance](https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies), [yt-dlp cookie FAQ](https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp), and [yt-dlp EJS setup](https://github.com/yt-dlp/yt-dlp/wiki/EJS).
