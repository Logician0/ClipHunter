"use client";
import Link from "next/link";
import { LayoutControl, Settings } from "./controls";
import ClipEditor from "./clip-editor";
import ClipPublishDialog from "./clip-publish-dialog";
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
  sourceAvailable?: boolean;
  sourceBytes?: number;
  previewVersion?: number;
  sourceVersion?: number;
  originalStart?: number;
  originalEnd?: number;
  job?: {phase?:string;fraction?:number|null;etaSeconds?:number|null};
};
type Chunk = {
  id: string;
  hour: number;
  status: string;
  error?: string;
  stage?: string;
  duration?: number;
  progress?: number | null;
  etaSeconds?: number | null;
  sourceAvailable?: boolean;
  sourceBytes?: number;
  sparse?: boolean;
  scanMethod?: "chat" | "audio" | "none";
  chatStatus?: string;
  scanWarning?: string;
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
type ChatHeatmap = { binSeconds:number; duration:number; posts:number[]; reactions:number[]; viewerPosts:number[]; status:string };
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
    <span>{data && !data.done ? (data.speed > 0 ? formatBytes(data.speed) + "/s" : "Measuring speed…") + (fraction !== null ? " · about " + fraction + "%" : "") + (data.estimatedTotal && data.speed>0 ? ` · about ${Math.ceil((data.estimatedTotal-data.bytes)/data.speed/60)} min left` : "") : ""}</span>
  </div>;
}
function ProcessProgress({ label, fraction, etaSeconds }: { label: string; fraction?: number | null; etaSeconds?: number | null }) {
  const percent = fraction == null ? null : Math.round(fraction * 100);
  return <div className="processProgress" role="status" aria-live="polite"><div className="processTop"><span className="processSpinner" aria-hidden="true"/><strong>{label}</strong><span>{percent == null ? "0%" : `~${percent}%`}</span></div><div className={`processTrack ${percent == null ? "indeterminate" : ""}`}><span style={percent == null ? undefined : { width: `${percent}%` }}/></div><small>{etaSeconds != null && etaSeconds>0 ? `About ${Math.ceil(etaSeconds/60)} min remaining` : "Stage progress · time remaining becomes available as source data arrives"}</small></div>;
}
function AudienceMap({chunk,api,onMoment}:{chunk:Chunk;api:(path:string)=>Promise<ChatHeatmap>;onMoment:(seconds:number)=>void}) {
  const [map,setMap]=useState<ChatHeatmap|null>(null);
  useEffect(()=>{
    let active=true;
    const read=()=>{void api(`/chunks/${chunk.id}/chat-heatmap`).then(value=>{if(active)setMap(value)}).catch(()=>{});};
    read();
    const timer=chunk.status==='scanning'?setInterval(read,5000):undefined;
    return ()=>{active=false;if(timer)clearInterval(timer)};
  },[chunk.id,chunk.status,api]);
  if(!map||!Array.isArray(map.posts)||!map.posts.length)return null;
  const max=Math.max(1,...map.posts);
  const total=map.posts.reduce((sum,value)=>sum+value,0);
  return <div className="audienceMap"><div className="audienceMapHeader"><div><strong>Audience activity</strong><span>{total.toLocaleString()} messages · {map.binSeconds}s intervals</span></div><span>{map.status==='available'?'Chat replay':map.status==='partial'?'Partial chat replay':map.status==='pending'?'Reading chat…':'Chat unavailable'}</span></div>
    <div className="audienceBars" role="group" aria-label="Stream chat activity by time interval">{map.posts.map((count,index)=>{
      const at=index*map.binSeconds;
      const reaction=map.reactions[index]||0;
      const hot=count>0&&count>=max*.55;
      return <button type="button" key={index} className={hot?'audienceBar hot':'audienceBar'} title={`${stamp(at)} · ${count} messages · ${reaction} reactions · choose this moment`} aria-label={`${stamp(at)}, ${count} chat messages, ${reaction} reactions. Choose moment.`} style={{height:`${Math.max(3,Math.round(100*Math.sqrt(count/max)))}%`}} onClick={()=>onMoment(at)}/>;
    })}</div><div className="audienceAxis"><span>0:00</span><span>{stamp(map.duration/2)}</span><span>{stamp(map.duration)}</span></div><p>Peaks show when chat moved faster. Select a bar to prepare a clip around that moment.</p></div>;
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
  const [publishing,setPublishing]=useState(false);
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
          <Link className="btn clipIconAction" href={"/edit/" + h.id} title="Edit clip" aria-label={`Edit ${h.title}`}>✎</Link>
          <button className="clipIconAction" title="Publish to YouTube" aria-label={`Publish ${h.title} to YouTube`} onClick={()=>setPublishing(true)}>▶</button>
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
          <a download={h.title + ".mp4"} className="btn clipIconAction" href={h.clip} title="Download MP4" aria-label={`Download ${h.title}`}>↓</a>
        </div>
      </div>
      {publishing&&<ClipPublishDialog id={h.id} title={h.title} api={api} onClose={()=>setPublishing(false)}/>}
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
  const [publishing,setPublishing]=useState(false);
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
            src={h.clip || (h.preview ? `${h.preview}?v=${h.previewVersion||0}` : undefined)}
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
      {["preparing","previewing","rendering","queued","expanding"].includes(h.status||"")&&<ProcessProgress label={h.job?.phase||({preparing:"Downloading selected moment",previewing:"Rendering preview",rendering:"Exporting clip",queued:"Queued",expanding:"Downloading more footage"}[h.status as "preparing"|"previewing"|"rendering"|"queued"|"expanding"])} fraction={h.job?.fraction} etaSeconds={h.job?.etaSeconds}/>}
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
          {stamp(offset + (h.originalStart??h.start))} – {stamp(offset + (h.originalEnd??h.end))} ·{" "}
          {Math.round(h.end - h.start)}s
        </code>
        {h.error && <p className="err">{h.error}</p>}
        <div className="row">
          {sourceAvailable && (h.preview || h.clip) && <Link className="clipIconAction" href={"/edit/" + h.id} title="Edit clip" aria-label={`Edit ${h.title}`}>✎</Link>}
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
          <button className="clipIconAction" disabled={!h.clip} title={h.clip?"Publish to YouTube":"Render clip before publishing"} aria-label={`Publish ${h.title} to YouTube`} onClick={()=>setPublishing(true)}>▶</button>
          {h.clip&&<a className="clipIconAction" href={h.clip} download={h.title + ".mp4"} title="Download MP4" aria-label={`Download ${h.title}`}>↓</a>}
        </div>
        {(["previewing","rendering","queued"].includes(h.status || "")) && <ProcessProgress label={h.status === "previewing" ? "Rendering preview" : h.status === "rendering" ? "Rendering final clip" : "Waiting to render"} />}
        {publishing&&<ClipPublishDialog id={h.id} title={h.title} api={api} onClose={()=>setPublishing(false)}/>}
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
    [confirmPwd, CP] = useState(""),
    [setupRequired, SR] = useState(false),
    [busy, BY] = useState(false),
    [hour, H] = useState(""),
    [manualMoment, MM] = useState(""),
    [selected, S] = useState<string[]>([]),
    [filter, F] = useState("");
  const reload = useCallback(async () => {
    try {
      const d = await api("/state");
      P(d.projects || []);
      AU("ready");
      C("");
    } catch (e) {
      if ((e as { status?: number }).status === 401) {
        AU("login");
        try { const status=await api('/auth/status'); SR(!!status.setupRequired); } catch { /* Keep sign-in available. */ }
      }
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
    MM("");
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
                Settings · YouTube
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
            <h1>{setupRequired?'Create your studio password':'Open your studio'}</h1>
            {setupRequired&&<p>Choose a password for this computer. It protects this local workspace and its connected YouTube channel.</p>}
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void action(async () => {
                  if(setupRequired&&pwd!==confirmPwd)throw new Error('Passwords do not match');
                  await api(setupRequired?"/setup":"/login", "POST", { password: pwd });
                  PW("");
                  CP("");
                  if (route[0] === "login") router.replace("/");
                });
              }}
            >
              <label htmlFor="pass">{setupRequired?'New password':'Workspace password'}</label>
              {!setupRequired&&<details><summary>Existing installation?</summary><p>If you have not changed your original password, find <code>APP_PASSWORD=</code> in your private <code>.env</code> file. After signing in, choose your own password in Settings.</p></details>}
              <input
                id="pass"
                type="password"
                value={pwd}
                autoComplete={setupRequired?'new-password':'current-password'}
                autoFocus
                onChange={(e) => PW(e.target.value)}
                required minLength={setupRequired?10:undefined}
              />
              {setupRequired&&<><label htmlFor="confirm-pass">Confirm password</label><input id="confirm-pass" type="password" autoComplete="new-password" value={confirmPwd} onChange={e=>CP(e.target.value)} required minLength={10}/></>}
              <button className="primary" disabled={busy}>
                {setupRequired?'Create and enter studio':'Enter studio'}
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
                  {chunk?.sourceAvailable && !chunk.sparse && highlights.length > 0 && (
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
                      <span>{c.status === "ready" && c.sparse ? c.highlights.some(h => ["preparing","previewing"].includes(h.status || "")) ? "Preparing suggested clips" : c.highlights.length ? `${c.highlights.length} suggested moments` : "No suggestions yet" : c.sourceAvailable ? c.stage || c.status : c.status === "ready" ? "Source removed" : c.stage || c.status}</span>
                    </button>
                  ))}
                  {chunk?.sourceAvailable && <details className="storageControls"><summary>Storage · {formatBytes(chunk.sourceBytes || 0)}</summary><p>Remove this hour&apos;s downloaded source video and any temporary stream cache. Finished clips and previews stay. You will need the source again to edit or render this hour.</p><button className="dangerButton" disabled={busy || !["ready","error"].includes(chunk.status) || chunk.highlights.some(h => ["queued","rendering","previewing","preparing","expanding"].includes(h.status || ""))} onClick={() => {
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
                  {chunk?.status === "ready" && chunk?.scanMethod && <p className="scanSummary">{chunk.scanMethod === "chat" ? "Highlights found from audience activity in chat replay." : chunk.scanMethod === "audio" ? "Chat replay was unavailable or inconclusive; these suggestions use audio and speech activity. Review each moment." : "No reliable highlight signal was available for this hour."} {chunk.scanWarning && <span>{chunk.scanWarning}</span>}</p>}
                  {chunk && <AudienceMap chunk={chunk} api={api} onMoment={seconds=>MM(stamp(seconds))}/>}
                  {chunk?.status==='ready'&&(chunk.sparse||chunk.sourceAvailable)&&<form className="manualClipForm" onSubmit={event=>{event.preventDefault();const value=manualMoment.trim();if(!/^\d{1,2}:\d{2}(?::\d{2})?$/.test(value)){E('Enter a specific time such as 12:30 or 1:12:30');return}const parts=value.split(':').map(Number);if(parts.slice(1).some(part=>part>=60)){E('Minutes and seconds must be below 60');return}const seconds=parts.reduce((total,part)=>total*60+part,0);void action(async()=>{await api(`/chunks/${chunk.id}/manual-clip`,'POST',{start:seconds})})}}><label>Choose a moment <input aria-label="Manual clip start" value={manualMoment} onChange={event=>MM(event.target.value)} required placeholder="mm:ss or h:mm:ss"/></label><button className="primary" disabled={busy}>Prepare clip here</button></form>}
                  {chunk?.status === "ready" && chunk.sparse && <button className="rescanButton" disabled={busy} onClick={()=>void action(async()=>{await api(`/chunks/${chunk.id}/rescan`,"POST",{})})}>Recheck this hour</button>}
                  {chunk?.status === "scanning" && chunk.stage === "Downloading" && <DownloadProgress chunkId={chunk.id} />}
                  {chunk?.status === "scanning" && chunk.stage !== "Downloading" && <ProcessProgress label={chunk.stage || "Processing"} fraction={chunk.progress} etaSeconds={chunk.etaSeconds} />}
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
                            sourceAvailable={h.sourceAvailable ?? (chunk?.sourceAvailable !== false)}
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
                          ? <p>No clips were suggested for this hour. Recheck the hour or choose an exact moment yourself.</p>
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
                <p>Find audience peaks and speech highlights, then download only the selected video windows.</p>
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
