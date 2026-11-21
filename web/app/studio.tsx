"use client";
import Link from "next/link";
import { LayoutControl, Settings } from "./controls";
import ClipEditor from "./clip-editor";
import { useRouter } from "next/navigation";
import { FormEvent, useCallback, useEffect, useState } from "react";

type Highlight = {
  id: string;
  start: number;
  end: number;
  title: string;
  clip?: string;
  preview?: string;
  status?: string;
  error?: string;
  score?: number;
  reason?: string;
};
type Chunk = {
  id: string;
  hour: number;
  status: string;
  error?: string;
  stage?: string;
  duration?: number;
  progress?: number | null;
  sourceAvailable?: boolean;
  sourceBytes?: number;
  highlights: Highlight[];
};
type Project = {
  id: string;
  url: string;
  title: string;
  chunks: Chunk[];
  isLive?: boolean;
  recording?: boolean;
};
function formatBytes(value: number) {
  if (value < 1024) return value + " B";
  const unit = Math.min(3, Math.floor(Math.log(value) / Math.log(1024)));
  return (value / 1024 ** unit).toFixed(1) + " " + ["B", "KB", "MB", "GB"][unit];
}
function DownloadProgress({ chunkId }: { chunkId: string }) {
  const [data, setData] = useState<{ bytes: number; estimatedTotal: number | null; done: boolean; speed: number } | null>(null);
  useEffect(() => {
    let active = true;
    let previous: { bytes: number; at: number } | null = null;
    const poll = async () => {
      try {
        const response = await fetch("/progress/" + chunkId, { cache: "no-store" });
        if (!response.ok) return;
        const next = await response.json();
        const now = Date.now();
        const speed = previous && next.bytes >= previous.bytes ? (next.bytes - previous.bytes) * 1000 / Math.max(1, now - previous.at) : 0;
        previous = { bytes: next.bytes, at: now };
        if (active) setData({ ...next, speed });
      } catch { /* Keep the last measurement during a connection gap. */ }
    };
    void poll();
    const timer = setInterval(poll, 3500);
    return () => { active = false; clearInterval(timer); };
  }, [chunkId]);
  const fraction = data?.estimatedTotal ? Math.min(99, Math.round(data.bytes / data.estimatedTotal * 100)) : null;
  return <div className="downloadProgress" role="status">
    <strong>{data?.done ? "Download complete" : "Downloading source video"}</strong>
    <progress max="100" value={data?.done ? 100 : fraction ?? undefined} aria-label="Source download progress" />
    <span>{data ? formatBytes(data.bytes) + (data.estimatedTotal ? " of about " + formatBytes(data.estimatedTotal) : " received · total unknown") : "Connecting to downloader…"}</span>
    <span>{data && !data.done ? (data.speed > 0 ? formatBytes(data.speed) + "/s" : "Measuring speed…") + (fraction !== null ? " · about " + fraction + "%" : "") : ""}</span>
  </div>;
}
function ProcessProgress({ label, fraction }: { label: string; fraction?: number | null }) {
  const percent = fraction == null ? null : Math.round(fraction * 100);
  return <div className="processProgress" role="status" aria-live="polite"><div className="processTop"><span className="processSpinner" aria-hidden="true"/><strong>{label}</strong><span>{percent == null ? "Working…" : percent + "%"}</span></div><div className={`processTrack ${percent == null ? "indeterminate" : ""}`}><span style={percent == null ? undefined : { width: `${percent}%` }}/></div><small>{label === "Transcribing" ? "Turning speech into timed captions" : label === "Finding moments" ? "Checking video, audio and transcript" : label === "Preparing previews" ? "Rendering playable vertical previews" : "Processing the footage"}</small></div>;
}
const stamp = (s: number) =>
  new Date(Math.max(0, s) * 1000).toISOString().slice(11, 19);
const clips = (p: Project) =>
  p.chunks.flatMap((c) => c.highlights || []).filter((h) => h.clip);
function platform(url: string) {
  try {
    const host = new URL(url).hostname.replace(/^www\./, "");
    return host.includes("youtu")
      ? "YouTube"
      : host.includes("twitch")
        ? "Twitch"
        : host.includes("kick")
          ? "Kick"
          : host;
  } catch {
    return "Stream";
  }
}
function Brand() {
  return (
    <Link className="brand" href="/" aria-label="ClipHunter home">
      <svg viewBox="0 0 32 32" aria-hidden="true">
        <path d="M4 8H15L10 14H4ZM18 8H29L16 24H5Z" fill="currentColor" />
      </svg>
      Clip<span>Hunter</span>
    </Link>
  );
}
async function api(path: string, method = "GET", body?: unknown) {
  const r = await fetch("/api" + path, {
    method,
    cache: "no-store",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const d = await r.json().catch(() => ({}));
  if (!r.ok)
    throw Object.assign(
      new Error(
        d.error?.message ||
          (typeof d.error === "string"
            ? d.error
            : "Request failed (" + r.status + ")"),
      ),
      { status: r.status },
    );
  return d;
}
function Tile({ h }: { h: Highlight }) {
  const [copyLabel, setCopyLabel] = useState("Copy title");
  return (
    <article className="tile">
      <video controls playsInline preload="metadata" src={h.clip} />
      <div className="tilebody">
        <span className="small">FINISHED CLIP</span>
        <h3>{h.title}</h3>
        {(h.score != null || h.reason) && (
          <p className="reason">
            {h.score != null ? h.score + "/100 · " : ""}
            {h.reason}
          </p>
        )}
        <div className="row">
          <Link className="btn" href={"/edit/" + h.id}>Edit clip</Link>
          <button
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(h.title);
                setCopyLabel("Copied");
              } catch {
                setCopyLabel("Select the title above");
              }
            }}
          >
            {copyLabel}
          </button>
          <a download={h.title + ".mp4"} className="btn" href={h.clip}>
            Download MP4
          </a>
        </div>
      </div>
    </article>
  );
}
function Candidate({
  h,
  offset,
  onRender,
  selected,
  setSelected,
  pending,
  sourceAvailable,
}: {
  h: Highlight;
  offset: number;
  onRender: () => void;
  selected: boolean;
  setSelected: () => void;
  pending: boolean;
  sourceAvailable: boolean;
}) {
  return (
    <article
      className="tile"
      tabIndex={0}
      aria-label={h.title}
      onKeyDown={(e) => {
        if (e.target !== e.currentTarget || e.altKey || e.metaKey || e.ctrlKey)
          return;
        const video = e.currentTarget.querySelector("video");
        const key = e.key.toLowerCase();
        if (
          ![
            "s",
            "r",
            "k",
            " ",
            "arrowleft",
            "arrowright",
          ].includes(key)
        )
          return;
        e.preventDefault();
        if (key === "s") setSelected();
        if (
          key === "r" &&
          !pending &&
          h.status !== "queued" &&
          h.status !== "rendering"
        )
          onRender();
        if (key === "k") video?.pause();
        if (key === " " && video) {
          if (video.paused) void video.play().catch(() => {});
          else video.pause();
        }
        if (key === "arrowleft")
          (e.currentTarget.previousElementSibling as HTMLElement)?.focus();
        if (key === "arrowright")
          (e.currentTarget.nextElementSibling as HTMLElement)?.focus();
      }}
    >
      <div className="preview">
        {h.preview || h.clip ? (
          <video
            src={h.clip || h.preview}
            playsInline
            controls
            muted
            preload="metadata"
          />
        ) : (
          <div className="placeholder">
            {h.error ? "Preview unavailable" : "Preparing preview"}
          </div>
        )}
      </div>
      <div className="tilebody">
        <label className="check">
          <input type="checkbox" checked={selected} onChange={setSelected} />
          Select clip
        </label>
        <h3>{h.title}</h3>
        {(h.score != null || h.reason) && (
          <p className="reason">
            {h.score != null ? h.score + "/100 · " : ""}
            {h.reason}
          </p>
        )}
        <code>
          {stamp(offset + h.start)} – {stamp(offset + h.end)} ·{" "}
          {Math.round(h.end - h.start)}s
        </code>
        {h.error && <p className="err">{h.error}</p>}
        <div className="row">
          {sourceAvailable && (h.preview || h.clip) && <Link href={"/edit/" + h.id}>Edit clip</Link>}
          <button
            onClick={onRender}
            disabled={
              pending || !sourceAvailable || h.status === "rendering" || h.status === "queued"
            }
          >
            {h.status === "rendering"
              ? "Rendering…"
              : h.status === "queued"
                ? "Queued"
                : "Render clip"}
          </button>
          {h.clip && (
            <a href={h.clip} download={h.title + ".mp4"}>
              Download
            </a>
          )}
        </div>
        {(["previewing","rendering","queued"].includes(h.status || "")) && <ProcessProgress label={h.status === "previewing" ? "Rendering preview" : h.status === "rendering" ? "Rendering final clip" : "Waiting to render"} />}
      </div>
    </article>
  );
}
export default function Studio({ route }: { route: string[] }) {
  const router = useRouter(),
    [projects, P] = useState<Project[]>([]),
    [auth, AU] = useState("loading"),
    [err, E] = useState(""),
    [conn, C] = useState(""),
    [url, U] = useState(""),
    [pwd, PW] = useState(""),
    [busy, BY] = useState(false),
    [hour, H] = useState(""),
    [selected, S] = useState<string[]>([]),
    [filter, F] = useState("");
  const reload = useCallback(async () => {
    try {
      const d = await api("/state");
      P(d.projects || []);
      AU("ready");
      C("");
    } catch (e) {
      if ((e as { status?: number }).status === 401) AU("login");
      else C((e as Error).message);
    }
  }, []);
  useEffect(() => {
    void reload();
    const id = setInterval(reload, 3500);
    return () => clearInterval(id);
  }, [reload]);
  useEffect(() => {
    H("");
    S([]);
    E("");
  }, [route.join("/")]);
  const project = projects.find((p) => String(p.id) === route[1]),
    library = route.includes("clips"),
    total = projects.flatMap(clips).length;
  const listedClips = projects
    .filter((p) => !(route[1] || filter) || String(p.id) === (route[1] || filter))
    .flatMap(clips);
  const editorProject = projects.find((p) => p.chunks.some((c) => c.highlights.some((h) => String(h.id) === route[1])));
  const editorChunk = editorProject?.chunks.find((c) => c.highlights.some((h) => String(h.id) === route[1]));
  const editorClip = editorChunk?.highlights.find((h) => String(h.id) === route[1]);
  const chunk =
      project?.chunks.find((c) => String(c.id) === hour) ||
      project?.chunks.at(-1),
    highlights = chunk?.highlights || [];
  const action = async (fn: () => Promise<void>) => {
    BY(true);
    E("");
    try {
      await fn();
      await reload();
    } catch (e) {
      E((e as Error).message);
    } finally {
      BY(false);
    }
  };
  const submit = (ev: FormEvent) => {
    ev.preventDefault();
    void action(async () => {
      const d = await api("/projects", "POST", { url: url.trim() });
      const id = d.id ?? d.project?.id;
      if (id != null) router.push("/p/" + id);
      U("");
    });
  };
  const render = (id: string) =>
    api("/highlights/" + id + "/render", "POST", {});
  const login = auth === "login" || (route[0] === "login" && auth !== "ready");
  return (
    <div className={login || route[0] === "edit" ? "appShell editorShell" : "appShell studioShell"}>
      <header>
        <div className="navwrap">
          <Brand />
          {!login && (
            <nav>
              <Link
                aria-current={
                  !library && route[0] !== "settings" ? "page" : undefined
                }
                href="/"
              >
                Projects
              </Link>
              <Link aria-current={library ? "page" : undefined} href="/clips">
                Clips <span>{total}</span>
              </Link>
              <Link
                aria-current={route[0] === "settings" ? "page" : undefined}
                href="/settings"
              >
                Settings
              </Link>
            </nav>
          )}
          <div className="studioLabel">LOCAL STUDIO</div>
        </div>
      </header>
      <main>
        {conn && (
          <p className="alert" role="alert">
            Connection issue · {conn}
          </p>
        )}
        {err && (
          <p className="alert" role="alert">
            {err}
          </p>
        )}
        {login ? (
          <section className="login">
            <span className="small">WORKSPACE ACCESS</span>
            <h1>Open your studio</h1>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void action(async () => {
                  await api("/login", "POST", { password: pwd });
                  PW("");
                  if (route[0] === "login") router.replace("/");
                });
              }}
            >
              <label htmlFor="pass">Workspace password</label>
              <details><summary>Find your local password</summary><p>In Finder, press Command + Shift + G and enter <code>~/ClipHunter</code>. Press Command + Shift + . to show hidden files. Open <code>.env</code> in TextEdit and copy the value after <code>APP_PASSWORD=</code>.</p></details>
              <input
                id="pass"
                type="password"
                value={pwd}
                autoComplete="current-password"
                autoFocus
                onChange={(e) => PW(e.target.value)}
                required
              />
              <button className="primary" disabled={busy}>
                Enter studio
              </button>
            </form>
          </section>
        ) : auth === "loading" ? (
          <p role="status">Connecting to your studio…</p>
        ) : route[0] === "settings" ? (
          <Settings api={api} />
        ) : route[0] === "edit" ? (
          editorClip && editorChunk && editorProject ? <ClipEditor id={route[1]} clip={editorClip} chunk={editorChunk} projectId={String(editorProject.id)} api={api} reload={reload} /> : <p role="status">Loading clip editor…</p>
        ) : library ? (
          <>
            <div className="heading">
              <div>
                <span className="small">CLIP LIBRARY</span>
                <h1>Rendered clips</h1>
              </div>
              <select
                aria-label="Filter by project"
                value={route[1] || filter}
                onChange={(e) => {
                  F(e.target.value);
                  if (route[1]) router.push("/clips");
                }}
              >
                <option value="">All projects</option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.title || p.url}
                  </option>
                ))}
              </select>
            </div>
            {(route[1] || filter) && (
              <a
                className="btn"
                href={"/api/projects/" + (route[1] || filter) + "/zip"}
                download="ClipHunter-clips.zip"
              >
                Download project ZIP
              </a>
            )}
            {listedClips.length > 0 && (
              <button className="btn" disabled={busy} onClick={() => {
                const picker = (window as Window & { showDirectoryPicker?: () => Promise<FileSystemDirectoryHandle> }).showDirectoryPicker;
                if (!picker) { E("Folder selection needs a compatible browser such as Chrome or Edge. Use Download MP4 instead."); return; }
                void picker.call(window).then((directory) => action(async () => {
                  for (const clip of listedClips) {
                    const response = await fetch(clip.clip!, { credentials: "same-origin" });
                    if (!response.ok) throw new Error("Could not download clip " + clip.id);
                    const file = await directory.getFileHandle("clip-" + clip.id + ".mp4", { create: true });
                    const writer = await file.createWritable();
                    await writer.write(await response.blob());
                    await writer.close();
                  }
                })).catch((error) => { if (error?.name !== "AbortError") E(error.message); });
              }}>Save all clips to a folder</button>
            )}
            <div className="grid">
              {listedClips.map((h) => (
                  <Tile h={h} key={h.id} />
                ))}
            </div>
            {!projects
              .filter(
                (p) =>
                  !(route[1] || filter) ||
                  String(p.id) === (route[1] || filter),
              )
              .some((p) => clips(p).length > 0) && (
              <div className="empty">Your rendered clips will appear here.</div>
            )}
          </>
        ) : route[0] === "p" ? (
          project ? (
            <>
              <Link className="back" href="/">
                ‹ All projects
              </Link>
              <div className="heading">
                <div>
                  <span className="small">
                    {platform(project.url).toUpperCase()} PROJECT
                  </span>
                  <h1>{project.title || "Stream project"}</h1>
                  <a
                    className="source"
                    href={project.url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Open original stream ↗
                  </a>
                </div>
                {clips(project).length > 0 && (
                  <Link className="btn" href={"/p/" + project.id + "/clips"}>
                    Open clips
                  </Link>
                )}
              </div>
              <div className="workspace">
                <aside>
                  <h2>Stream hours</h2>
                  {chunk?.sourceAvailable && highlights.length > 0 && (
                    <LayoutControl
                      key={chunk.id}
                      chunk={chunk.id}
                      api={api}
                      afterSave={reload}
                    />
                  )}
                  {project.isLive && (
                    <p className="recording">
                      {project.recording
                        ? "Live · Recording"
                        : "Recording stopped"}
                    </p>
                  )}
                  {project.chunks.map((c, i) => (
                    <button
                      className={"hour " + (c.id === chunk?.id ? "active" : "")}
                      key={c.id}
                      onClick={() => {
                        H(String(c.id));
                        S([]);
                      }}
                    >
                      <strong>Hour {i + 1}</strong>
                      <span>{c.sourceAvailable ? c.stage || c.status : c.status === "ready" ? "Source removed" : c.stage || c.status}</span>
                    </button>
                  ))}
                  {chunk?.sourceAvailable && <details className="storageControls"><summary>Storage · {formatBytes(chunk.sourceBytes || 0)}</summary><p>Remove this hour&apos;s downloaded source video and any temporary stream cache. Finished clips and previews stay. You will need the source again to edit or render this hour.</p><button className="dangerButton" disabled={busy || !["ready","error"].includes(chunk.status) || chunk.highlights.some(h => ["queued","rendering","previewing"].includes(h.status || ""))} onClick={() => {
                    if (!window.confirm(`Delete the downloaded video for hour ${chunk.hour}? Finished clips will stay, but this hour can no longer be edited or rendered.`)) return;
                    void action(async () => { await api(`/chunks/${chunk.id}/source`, "DELETE"); });
                  }}>Delete downloaded hour video</button></details>}
                  <button
                    className="primary"
                    disabled={
                      busy ||
                      project.chunks.some((c) =>
                        [
                          "queued",
                          "scanning",
                          "running",
                          "downloading",
                          "analyzing",
                          "transcribing",
                        ].includes(c.status),
                      )
                    }
                    onClick={() =>
                      void action(async () => {
                        await api(
                          "/projects/" + project.id + "/scan",
                          "POST",
                          {},
                        );
                        H("");
                        S([]);
                      })
                    }
                  >
                    {project.isLive
                      ? "Scan recorded footage"
                      : chunk?.error
                        ? "Retry scan"
                        : project.chunks.length
                          ? "Scan next hour"
                          : "Scan first hour"}
                  </button>
                  {project.recording && (
                    <button
                      className="hour"
                      disabled={busy}
                      onClick={() =>
                        void action(async () => {
                          await api(
                            "/projects/" + project.id + "/stop",
                            "POST",
                            {},
                          );
                        })
                      }
                    >
                      Stop recording
                    </button>
                  )}
                </aside>
                <section>
                  <h2>
                    {chunk
                      ? "Hour " +
                        (project.chunks.indexOf(chunk) + 1) +
                        " highlights"
                      : "Highlights"}
                  </h2>
                  {chunk?.error && <p className="alert">{chunk.error}</p>}
                  {chunk?.status === "scanning" && chunk.stage === "Downloading" && <DownloadProgress chunkId={chunk.id} />}
                  {chunk?.status === "scanning" && chunk.stage !== "Downloading" && <ProcessProgress label={chunk.stage || "Processing"} fraction={chunk.progress} />}
                  {chunk?.error?.includes("sign-in/bot check") && (
                    <p><a href={project.url} target="_blank" rel="noopener noreferrer">Open this stream on YouTube</a> · <Link href="/settings">Import a YouTube session</Link>, then choose Retry scan.</p>
                  )}
                  {highlights.length ? (
                    <>
                      <details className="shortcuts">
                        <summary>Keyboard shortcuts</summary>
                        <p>
                          Focus a card. Space plays or pauses, K pauses, S
                          selects, and R renders. Left and right arrows switch
                          cards. Open Edit clip to adjust the timeline and layout.
                        </p>
                      </details>
                      <div className="grid">
                        {highlights.map((h) => (
                          <Candidate
                            h={h}
                            offset={3600 * ((chunk?.hour || 1) - 1)}
                            key={h.id}
                            selected={selected.includes(h.id)}
                            setSelected={() =>
                              S((prev) =>
                                prev.includes(h.id)
                                  ? prev.filter((i) => i !== h.id)
                                  : [...prev, h.id],
                              )
                            }
                            pending={busy}
                            sourceAvailable={chunk?.sourceAvailable !== false}
                            onRender={() =>
                              void action(async () => {
                                await render(h.id);
                              })
                            }
                          />
                        ))}
                      </div>
                      <div className="actions">
                        <strong>{selected.length} selected</strong>
                        <button
                          onClick={() =>
                            S(
                              selected.length === highlights.length
                                ? []
                                : highlights.map((h) => h.id),
                            )
                          }
                        >
                          {selected.length === highlights.length
                            ? "Clear"
                            : "Select all"}
                        </button>
                        <button
                          className="primary"
                          disabled={busy || !selected.length}
                          onClick={() =>
                            void action(async () => {
                              for (const id of selected) {
                                await render(id);
                                S((cur) => cur.filter((i) => i !== id));
                              }
                            })
                          }
                        >
                          Render selected
                        </button>
                      </div>
                    </>
                  ) : (
                    <div className="empty">
                      {chunk
                        ? chunk.status === "ready"
                          ? "No clear chat reaction burst was found in this hour. ClipHunter does not make random clips from speech. Try another hour with available stream chat."
                          : "Scan status · " + chunk.status
                        : "Scan the first hour to find highlights."}
                    </div>
                  )}
                </section>
              </div>
            </>
          ) : (
            <div className="empty">
              Project unavailable. <Link href="/">Return to projects</Link>
            </div>
          )
        ) : (
          <>
            <div className="intro dashboardHero"><div><span className="small">YOUR CREATIVE WORKSPACE</span><h1>Clip Studio</h1><p>Turn long streams into moments worth sharing.</p></div><div className="dashboardStats"><div><strong>{projects.length}</strong><span>Projects</span></div><div><strong>{projects.reduce((count,p)=>count+p.chunks.length,0)}</strong><span>Hours scanned</span></div><div><strong>{total}</strong><span>Finished clips</span></div></div></div>
            <section className="ingest">
              <div className="marker" aria-hidden="true">✦</div>
              <div>
                <h2>Scan a stream</h2>
                <p>Scans one hour at a time. Finds 4 to 5 clips per hour.</p>
                <form onSubmit={submit}>
                  <input
                    type="text"
                    aria-label="Stream URL"
                    placeholder="Paste a stream link, YouTube ID or Studio link"
                    value={url}
                    onChange={(e) => U(e.target.value)}
                    required
                  />
                  <button
                    className="primary"
                    disabled={busy || !url.trim()}
                  >
                    {busy ? "Starting…" : "Scan stream"}
                  </button>
                </form>
              </div>
            </section>
            <div className="sectiontitle">
              <h2>Recent projects</h2>
              <code>
                {projects.length}{" "}
                {projects.length === 1 ? "project" : "projects"}
              </code>
            </div>
            {projects.length ? (
              <div className="projects">
                {projects.map((p) => (
                  <Link className="project" href={"/p/" + p.id} key={p.id}>
                    <div className="projectVisual">{p.chunks.flatMap(c=>c.highlights).find(h=>h.preview||h.clip)?.preview||p.chunks.flatMap(c=>c.highlights).find(h=>h.clip)?.clip ? <video muted playsInline preload="metadata" src={p.chunks.flatMap(c=>c.highlights).find(h=>h.preview||h.clip)?.preview||p.chunks.flatMap(c=>c.highlights).find(h=>h.clip)?.clip}/> : <span>✦</span>}<small>{platform(p.url)}</small></div>
                    <div className="projectInfo"><span className="small">{platform(p.url).toUpperCase()}</span><h3>{p.title || p.url}</h3><code>{p.chunks.length} hours · {clips(p).length} rendered</code></div>
                  </Link>
                ))}
              </div>
            ) : (
              <div className="empty">
                <b>No projects yet</b>
                <p>Paste a stream link above to start your first scan.</p>
              </div>
            )}
          </>
        )}
      </main>
      <footer>
        <span>ClipHunter Studio</span>
        <span>Only clip streams you have permission to use.</span>
      </footer>
    </div>
  );
}
