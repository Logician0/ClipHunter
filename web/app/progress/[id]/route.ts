import { NextRequest, NextResponse } from "next/server";
import { stat, readFile, readdir } from "node:fs/promises";
import path from "node:path";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest, context: { params: Promise<{ id: string }> }) {
  const { id } = await context.params;
  if (!/^\d{1,12}$/.test(id)) return NextResponse.json({ error: "Invalid chunk" }, { status: 400 });
  const auth = await fetch(`${process.env.CLIPHUNTER_API_ORIGIN || "http://127.0.0.1:3101"}/api/state`, {
    headers: { cookie: request.headers.get("cookie") || "" },
    cache: "no-store",
  }).catch(() => null);
  if (!auth?.ok) return NextResponse.json({ error: "Sign in" }, { status: 401 });
  const folder = path.resolve(process.cwd(), "../data/chunks", id);
  const shared = path.resolve(process.cwd(), "../data/chunks");
  let names: string[] = [];
  try { names = await readdir(folder); } catch { return NextResponse.json({ bytes: 0, done: false }); }
  const candidates = names.filter((name) => /^capture\..*\.part$/.test(name));
  const sharedNames = await readdir(shared).catch(() => []);
  candidates.push(...sharedNames.filter((name) => /^cache-[a-f0-9]+\..*\.part$/.test(name)).map((name) => "../" + name));
  let bytes = 0;
  for (const name of candidates) {
    const size = await stat(path.resolve(folder, name)).then((s) => s.size).catch(() => 0);
    bytes = Math.max(bytes, size);
  }
  const done = names.includes("source.mp4");
  if (done && !bytes) bytes = await stat(path.join(folder, "source.mp4")).then((s) => s.size).catch(() => 0);
  let estimatedTotal: number | null = null;
  try {
    const estimate = JSON.parse(await readFile(path.join(folder, "download-estimate.json"), "utf8"));
    if (Number.isFinite(estimate.bytes) && estimate.bytes > 0) estimatedTotal = estimate.bytes;
  } catch { /* Some sources do not expose bitrate. */ }
  return NextResponse.json({ bytes, estimatedTotal, done }, { headers: { "Cache-Control": "no-store" } });
}
