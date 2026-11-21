"use client";
import { useEffect, useRef, useState, PointerEvent } from "react";

export type RequestFn = (
  path: string,
  method?: string,
  body?: unknown,
) => Promise<any>;
type Mode = "auto" | "full" | "split";
type Box = [number, number, number, number];
export type Layout = { mode: Mode; box?: Box };
const startingBox: Box = [0.65, 0.05, 0.3, 0.35];
export function Settings({ api }: { api: RequestFn }) {
  const [value, setValue] = useState<{
    model: string;
    maxDataGB: number;
  } | null>(null);
  const [message, setMessage] = useState(""),
    [saving, setSaving] = useState(false);
  useEffect(() => {
    let live = true;
    api("/settings")
      .then((data) => {
        if (live) setValue(data);
      })
      .catch((e) => {
        if (live) setMessage(e.message);
      });
    return () => {
      live = false;
    };
  }, [api]);
  return (
    <>
      <span className="small">WORKSPACE</span>
      <h1>Settings</h1>
      <section className="panel">
        {value ? (
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              setSaving(true);
              setMessage("");
              try {
                await api("/settings", "PUT", value);
                setMessage("Settings saved. To restart a failed project, return to it and choose Retry scan.");
              } catch (e) {
                setMessage((e as Error).message);
              } finally {
                setSaving(false);
              }
            }}
          >
            <label>
              Transcription model
              <select
                value={value.model}
                onChange={(e) => {
                  setMessage("");
                  setValue({ ...value, model: e.target.value });
                }}
              >
                {["tiny", "base", "small"].map((m) => (
                  <option key={m}>{m}</option>
                ))}
              </select>
            </label>
            <label>
              Maximum media storage (GB)
              <input
                type="number"
                min="2"
                max="100"
                step="1"
                value={value.maxDataGB}
                required
                onChange={(e) => {
                  setMessage("");
                  setValue({ ...value, maxDataGB: Number(e.target.value) });
                }}
              />
            </label>
            <button className="primary" disabled={saving}>
              {saving ? "Saving…" : "Save settings"}
            </button>
          </form>
        ) : (
          !message && <p>Loading settings…</p>
        )}
        <p role="status">{message}</p>
      </section>
      <section className="panel">
        <h2>YouTube access</h2>
        <p>If YouTube asks you to sign in or confirm you are human, open the stream in your browser and complete that step. A browser check alone does not grant the local downloader access. Export only YouTube cookies to a Netscape-format cookies.txt file, import it here, then retry the scan. This file is a sensitive sign-in credential; keep it private.</p>
        <label>Import YouTube cookies.txt
          <input type="file" accept=".txt,text/plain" onChange={async (e) => {
            const file=e.target.files?.[0];
            if (!file) return;
            setMessage("");
            try {
              if (file.size>300_000) throw new Error("Choose a YouTube-only cookies.txt file under 300 KB.");
              await api("/youtube-cookies","POST",{cookies:await file.text()});
              setMessage("YouTube session imported. Return to the project and choose Retry scan.");
            } catch (error) { setMessage((error as Error).message); }
            e.target.value="";
          }}/>
        </label>
        <a href="https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies" target="_blank" rel="noopener noreferrer">How to export YouTube cookies</a>
      </section>
    </>
  );
}
export function LayoutControl({
  chunk,
  initial,
  api,
  afterSave,
}: {
  chunk: string;
  initial?: Layout;
  api: RequestFn;
  afterSave: () => Promise<void>;
}) {
  const dialog = useRef<HTMLDialogElement>(null),
    start = useRef<[number, number] | null>(null);
  const [mode, modeSet] = useState<Mode>("auto"),
    [box, setBox] = useState<Box>(startingBox),
    [msg, M] = useState(""),
    [saving, saveBusy] = useState(false),
    [loaded, L] = useState(false),
    [detectedBox, D] = useState(false);
  function point(e: PointerEvent<HTMLDivElement>): [number, number] {
    const r = e.currentTarget.getBoundingClientRect();
    const clamp = (n: number) => Math.max(0, Math.min(1, n));
    return [
      clamp((e.clientX - r.left) / r.width),
      clamp((e.clientY - r.top) / r.height),
    ];
  }
  return (
    <>
      <button
        className="layoutbutton"
        onClick={async () => {
          modeSet(initial?.mode || "auto");
          setBox(initial?.box || startingBox);
          D(Boolean(initial?.box));
          M("");
          saveBusy(true);
          dialog.current?.showModal();
          try {
            const saved = await api("/chunks/" + chunk + "/layout");
            modeSet(saved.mode || "auto");
            setBox(saved.box || startingBox);
            D(Boolean(saved.box));
          } catch (e) {
            M((e as Error).message);
          } finally {
            saveBusy(false);
          }
        }}
      >
        Edit layout
      </button>
      <dialog ref={dialog} aria-labelledby="layout-title">
        <div className="heading">
          <h2 id="layout-title">Edit layout</h2>
          <button
            aria-label="Close layout editor"
            onClick={() => dialog.current?.close()}
          >
            Close
          </button>
        </div>
        <label>
          Vertical layout
          <select
            value={mode}
            disabled={saving}
            onChange={(e) => modeSet(e.target.value as Mode)}
          >
            <option value="auto">Auto-detect facecam</option>
            <option value="full">Full-frame gameplay</option>
            <option value="split">Gameplay and facecam</option>
          </select>
        </label>
        {mode === "split" && (
          <p>Drag across the source frame to select the facecam, or enter its position as percentages.</p>
        )}
        <div
          className="sourceframe"
          onPointerDown={(e) => {
                if (!loaded || mode !== "split") return;
                start.current = point(e);
                e.currentTarget.setPointerCapture(e.pointerId);
              }}
          onPointerMove={(e) => {
                if (!start.current || mode !== "split") return;
                const [x, y] = point(e),
                  [sx, sy] = start.current;
                const w = Math.abs(x - sx),
                  h = Math.abs(y - sy);
                if (w > 0.01 && h > 0.01)
                  setBox([Math.min(x, sx), Math.min(y, sy), w, h]);
              }}
          onPointerUp={() => {
                start.current = null;
              }}
          onPointerCancel={() => {
                start.current = null;
              }}
            >
              <img
                src={"/api/chunks/" + chunk + "/frame"}
                alt="Source frame for selecting the facecam"
                draggable={false}
                onLoad={() => L(true)}
                onError={() => L(false)}
              />
              {loaded && (mode === "split" || (mode === "auto" && detectedBox)) && (
                <span
                  className="bounding"
                  style={{
                    left: box[0] * 100 + "%",
                    top: box[1] * 100 + "%",
                    width: box[2] * 100 + "%",
                    height: box[3] * 100 + "%",
                  }}
                />
              )}
        </div>
        {mode === "split" && (
          <>
            <div className="boxfields">
              {["Left", "Top", "Width", "Height"].map((name, i) => (
                <label key={name}>
                  {name} (%)
                  <input
                    type="number"
                    min={i < 2 ? 0 : 1}
                    max="100"
                    value={Math.round(100 * box[i])}
                    onChange={(e) => {
                      const next = [...box] as Box;
                      next[i] = Number(e.target.value) / 100;
                      setBox(next);
                    }}
                  />
                </label>
              ))}
            </div>
          </>
        )}
        <button
          className="primary"
          disabled={saving}
          onClick={async () => {
            if (
              mode === "split" &&
              (box[2] <= 0 ||
                box[3] <= 0 ||
                box.some((n) => n < 0 || n > 1) ||
                box[0] + box[2] > 1.000001 ||
                box[1] + box[3] > 1.000001)
            ) {
              M("Keep the facecam inside the source frame.");
              return;
            }
            saveBusy(true);
            M("");
            try {
              await api("/chunks/" + chunk + "/layout", "PATCH", { mode, box });
              await afterSave();
              dialog.current?.close();
            } catch (e) {
              M((e as Error).message);
            } finally {
              saveBusy(false);
            }
          }}
        >
          {saving ? "Saving…" : "Save layout"}
        </button>
        <p role="alert">{msg}</p>
      </dialog>
    </>
  );
}
