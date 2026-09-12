import { open, readFile, stat } from "node:fs/promises";
import path from "node:path";

const FORWARD_FILE_PATH = path.join(process.cwd(), "public", "portfolio-impact-bull-bear-master.mp4");
const REVERSE_FILE_PATH = path.join(process.cwd(), "public", "portfolio-impact-bull-bear-master-reverse.mp4");
const CACHE_CONTROL = "public, max-age=86400, stale-while-revalidate=604800";

function filePathFor(request: Request) {
  const url = new URL(request.url);
  return url.searchParams.get("direction") === "reverse" ? REVERSE_FILE_PATH : FORWARD_FILE_PATH;
}

function commonHeaders(size: number) {
  return {
    "Accept-Ranges": "bytes",
    "Cache-Control": CACHE_CONTROL,
    "Content-Type": "video/mp4",
    "Content-Length": String(size),
  };
}

function parseRange(value: string, size: number) {
  if (!value.startsWith("bytes=") || value.includes(",")) return null;
  const [startPart = "", endPart = ""] = value.slice(6).split("-", 2);
  let start: number;
  let end: number;

  if (!startPart) {
    const suffixLength = Number(endPart);
    if (!Number.isInteger(suffixLength) || suffixLength <= 0) return null;
    start = Math.max(0, size - suffixLength);
    end = size - 1;
  } else {
    start = Number(startPart);
    end = endPart ? Number(endPart) : size - 1;
    if (!Number.isInteger(start) || !Number.isInteger(end)) return null;
  }

  if (start < 0 || start >= size || end < start) return null;
  end = Math.min(end, size - 1);
  return { start, end };
}

export async function HEAD(request: Request) {
  const filePath = filePathFor(request);
  try {
    const info = await stat(filePath);
    return new Response(null, { status: 200, headers: commonHeaders(info.size) });
  } catch {
    return new Response(null, { status: 404, headers: { "Cache-Control": "no-store" } });
  }
}

export async function GET(request: Request) {
  const filePath = filePathFor(request);
  let info;
  try {
    info = await stat(filePath);
  } catch {
    return new Response("Bull vs Bear master media ontbreekt", { status: 404, headers: { "Cache-Control": "no-store" } });
  }

  const rangeHeader = request.headers.get("range");
  if (!rangeHeader) {
    const file = await readFile(filePath);
    return new Response(file, { status: 200, headers: commonHeaders(info.size) });
  }

  const range = parseRange(rangeHeader, info.size);
  if (!range) {
    return new Response(null, {
      status: 416,
      headers: {
        "Accept-Ranges": "bytes",
        "Cache-Control": CACHE_CONTROL,
        "Content-Range": `bytes */${info.size}`,
        "Content-Type": "video/mp4",
      },
    });
  }

  const length = range.end - range.start + 1;
  const buffer = Buffer.allocUnsafe(length);
  const handle = await open(filePath, "r");
  try {
    await handle.read(buffer, 0, length, range.start);
  } finally {
    await handle.close();
  }

  return new Response(buffer, {
    status: 206,
    headers: {
      "Accept-Ranges": "bytes",
      "Cache-Control": CACHE_CONTROL,
      "Content-Length": String(length),
      "Content-Range": `bytes ${range.start}-${range.end}/${info.size}`,
      "Content-Type": "video/mp4",
    },
  });
}
