#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "Usage: $0 <bear-half.mp4> <bull-half.mp4> <neutral-poster.png|webp>" >&2
  exit 2
fi

BEAR_HALF="$1"
BULL_HALF="$2"
NEUTRAL="$3"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_VIDEO="$ROOT/public/portfolio-impact-bull-bear-master.mp4"
OUT_POSTER="$ROOT/public/portfolio-impact-bull-bear-neutral.webp"

for input in "$BEAR_HALF" "$BULL_HALF" "$NEUTRAL"; do
  [[ -s "$input" ]] || { echo "Missing input: $input" >&2; exit 3; }
done
command -v ffmpeg >/dev/null || { echo "ffmpeg is required" >&2; exit 4; }
command -v ffprobe >/dev/null || { echo "ffprobe is required" >&2; exit 4; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$ROOT/public"

ffmpeg -hide_banner -loglevel error -y -i "$BEAR_HALF" \
  -vf "reverse,fps=30,scale=1280:720:flags=lanczos,setsar=1" \
  -an -c:v libx264 -preset medium -crf 19 -pix_fmt yuv420p \
  -g 6 -keyint_min 6 -sc_threshold 0 "$TMP/bear-reversed.mp4"

ffmpeg -hide_banner -loglevel error -y -i "$BULL_HALF" \
  -vf "fps=30,scale=1280:720:flags=lanczos,setsar=1" \
  -an -c:v libx264 -preset medium -crf 19 -pix_fmt yuv420p \
  -g 6 -keyint_min 6 -sc_threshold 0 "$TMP/bull-normalized.mp4"

ffmpeg -hide_banner -loglevel error -y \
  -i "$TMP/bear-reversed.mp4" -i "$TMP/bull-normalized.mp4" \
  -filter_complex "[0:v]setpts=PTS-STARTPTS[bear];[1:v]setpts=PTS-STARTPTS[bull];[bear][bull]concat=n=2:v=1:a=0[joined];[joined]fps=30[v]" \
  -map "[v]" -an -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p \
  -g 6 -keyint_min 6 -sc_threshold 0 -movflags +faststart "$OUT_VIDEO"

ffmpeg -hide_banner -loglevel error -y -i "$NEUTRAL" \
  -vf "scale=1280:720:flags=lanczos" -frames:v 1 "$OUT_POSTER"

python - "$OUT_VIDEO" <<'PY'
import json, subprocess, sys
path = sys.argv[1]
info = json.loads(subprocess.check_output([
    'ffprobe','-v','error','-show_streams','-show_format','-of','json',path
], text=True))
video = next(s for s in info['streams'] if s.get('codec_type') == 'video')
duration = float(info['format']['duration'])
assert int(video['width']) == 1280, video
assert int(video['height']) == 720, video
assert 11.5 <= duration <= 12.5, duration
assert not any(s.get('codec_type') == 'audio' for s in info['streams'])
print(f"master ok: {duration:.3f}s {video.get('avg_frame_rate')} {video.get('codec_name')}")
PY

echo "$OUT_VIDEO"
echo "$OUT_POSTER"
