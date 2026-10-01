#!/usr/bin/env bash
# Flow Kit statusline for Claude Code
# Optimized: parallel curl + single-pass jq + no python
# ANSI colors: green=32, violet/magenta=35

G="\033[32m"  # green
V="\033[35m"  # violet
R="\033[0m"   # reset

# ── Claude session info (from stdin JSON, single jq call) ──
CLAUDE=""
if [ ! -t 0 ]; then
  read -r STDIN_JSON
  if [ -n "$STDIN_JSON" ]; then
    IFS='|' read -r model ctx_pct rl5h rl7d <<< "$(echo "$STDIN_JSON" | jq -r '[
      (.model.display_name // ""),
      ((.context_window.used_percentage // 0) | floor | tostring),
      ((.rate_limits.five_hour.used_percentage // 0) | floor | tostring),
      ((.rate_limits.seven_day.used_percentage // 0) | floor | tostring)
    ] | join("|")' 2>/dev/null)"
    if [ -n "$model" ]; then
      CLAUDE="${model} ctx:${G}${ctx_pct}%${R} rl:${G}${rl5h}%${R}/5h ${G}${rl7d}%${R}/7d"
    fi
  fi
fi

# ── GLA info (parallel fetch) ──
BASE="http://127.0.0.1:8100"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# Fetch all independent endpoints in parallel
curl -s --max-time 1 "$BASE/health" >"$TMP/health" 2>/dev/null &
curl -s --max-time 1 "$BASE/api/flow/credits" >"$TMP/credits" 2>/dev/null &
curl -s --max-time 1 "$BASE/api/active-project" >"$TMP/active_project" 2>/dev/null &
curl -s --max-time 1 "$BASE/api/projects" >"$TMP/projects" 2>/dev/null &
curl -s --max-time 1 "$BASE/api/requests/pending" >"$TMP/pending" 2>/dev/null &
curl -s --max-time 1 "$BASE/api/requests?status=PROCESSING" >"$TMP/processing" 2>/dev/null &
wait

# Browser transport health — single jq call
health=$(cat "$TMP/health")
if [ -z "$health" ]; then
  echo -e "${CLAUDE:+$CLAUDE | }GLA: ⚠ DOWN"
  exit 0
fi

IFS='|' read -r backend_ready session_ready auth lease reconciliation pending_intents paid_enabled <<< "$(echo "$health" | jq -r '[
  (.backend_ready // false | tostring),
  (.browser_session_ready // false | tostring),
  (.authentication // "unknown"),
  (.lease_held // false | tostring),
  (.reconciliation_required // false | tostring),
  (.pending_intents // 0 | tostring),
  (.paid_dispatch_enabled // false | tostring)
] | join("|")' 2>/dev/null)"

if [ "$backend_ready" = "true" ] && [ "$session_ready" = "true" ] && [ "$auth" = "authenticated" ] && [ "$lease" = "true" ]; then
  browser_icon="BR:${G}Ok${R}"
else
  browser_icon="BR:${V}✗${R}"
fi

recon_info=""
if [ "$reconciliation" = "true" ]; then
  recon_info=" ${V}Recon:!${pending_intents}${R}"
fi

if [ "$paid_enabled" = "true" ]; then
  paid_info=" ${V}Paid:Val${R}"
else
  paid_info=" Paid:Lock"
fi

# Credits/tier is business metadata; browser authentication comes from /health.
credits_info=""
tier=$(jq -r '.data.userPaygateTier // .userPaygateTier // empty' "$TMP/credits" 2>/dev/null)
case "$tier" in
  PAYGATE_TIER_ONE) credits_info="T1" ;;
  PAYGATE_TIER_TWO) credits_info="T2" ;;
  "") ;;
  *) credits_info="$tier" ;;
esac

# Project — use active-project endpoint (falls back to most recent)
ap=$(cat "$TMP/active_project" 2>/dev/null)
proj_id=$(echo "$ap" | jq -r '.project_id // empty' 2>/dev/null)
proj_name=$(echo "$ap" | jq -r '.project_name // empty' 2>/dev/null)
vid_id=$(echo "$ap" | jq -r '.video_id // empty' 2>/dev/null)

# Fallback to projects list if active-project endpoint unavailable
if [ -z "$proj_id" ]; then
  project=$(cat "$TMP/projects")
  if [ -z "$project" ] || [ "$project" = "[]" ]; then
    echo -e "${CLAUDE:+$CLAUDE | }GLA: ${browser_icon}${paid_info}${recon_info}"
    exit 0
  fi
  IFS='|' read -r proj_name proj_id <<< "$(echo "$project" | jq -r '.[-1] | [(.name // "?"), (.id // "")] | join("|")' 2>/dev/null)"
  vid_id=$(curl -s --max-time 1 "$BASE/api/videos?project_id=$proj_id" 2>/dev/null | jq -r '.[-1].id // ""' 2>/dev/null)
fi

if [ -z "$vid_id" ]; then
  echo -e "${CLAUDE:+$CLAUDE | }GLA: ${browser_icon}${paid_info}${recon_info} $(echo "$proj_name" | cut -c1-15)"
  exit 0
fi

# Fetch video for orientation
video=$(curl -s --max-time 1 "$BASE/api/videos/$vid_id" 2>/dev/null)

# Scenes — single jq call extracts all stats at once
scenes=$(curl -s --max-time 1 "$BASE/api/scenes?video_id=$vid_id" 2>/dev/null)
IFS='|' read -r total h_img h_vid h_up v_img v_vid v_up <<< "$(echo "$scenes" | jq -r '[
  length,
  ([.[] | select(.horizontal_image_status == "COMPLETED")] | length),
  ([.[] | select(.horizontal_video_status == "COMPLETED")] | length),
  ([.[] | select(.horizontal_upscale_status == "COMPLETED")] | length),
  ([.[] | select(.vertical_image_status == "COMPLETED")] | length),
  ([.[] | select(.vertical_video_status == "COMPLETED")] | length),
  ([.[] | select(.vertical_upscale_status == "COMPLETED")] | length)
] | map(tostring) | join("|")' 2>/dev/null)"

# Use video.orientation from API, fallback to heuristic
vid_orient=$(echo "$video" | jq -r '.orientation // empty' 2>/dev/null)
if [ "$vid_orient" = "HORIZONTAL" ]; then
  img_done=$h_img; vid_done=$h_vid; up_done=$h_up; ori_label="H"
elif [ "$vid_orient" = "VERTICAL" ]; then
  img_done=$v_img; vid_done=$v_vid; up_done=$v_up; ori_label="V"
elif [ "$h_img" != "0" ] || [ "$h_vid" != "0" ]; then
  img_done=$h_img; vid_done=$h_vid; up_done=$h_up; ori_label="H"
else
  img_done=$v_img; vid_done=$v_vid; up_done=$v_up; ori_label="V"
fi

# Queue
pending=$(jq 'length' "$TMP/pending" 2>/dev/null || echo 0)
processing=$(jq 'length' "$TMP/processing" 2>/dev/null || echo 0)

short_name=$(echo "$proj_name" | cut -c1-15)

# Project slug — fetch from API (Python slugify is authoritative)
proj_slug=$(curl -s --max-time 1 "$BASE/api/projects/$proj_id/output-dir" 2>/dev/null | jq -r '.slug // empty' 2>/dev/null)
if [ -z "$proj_slug" ]; then
  # Fallback: pure bash (lossy for non-ASCII)
  proj_slug=$(echo "$proj_name" | iconv -f UTF-8 -t ASCII//TRANSLIT 2>/dev/null | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/_/g' | tr -s '_' | sed 's/^_//;s/_$//')
fi

# 4K downloaded count
dl_count=0
if [ -d "output/${proj_slug}/4k" ]; then
  dl_count=$(ls "output/${proj_slug}/4k"/scene_*.mp4 2>/dev/null | wc -l | tr -d ' ')
fi

# TTS count
tts_count=0
if [ -d "output/${proj_slug}/tts" ]; then
  tts_count=$(ls "output/${proj_slug}/tts"/scene_*.wav 2>/dev/null | wc -l | tr -d ' ')
fi

flow_str=""
[ -n "$credits_info" ] && flow_str=" ${V}${credits_info}${R}"

# Queue: pending→processing/max
queue="${V}${pending}${R}→${V}${processing}${R}/5"

echo -e "${CLAUDE:+$CLAUDE | }GLA: ${browser_icon}${paid_info}${recon_info}${flow_str} ${short_name} ${ori_label} ${total}sc img:${V}${img_done}${R} vid:${V}${vid_done}${R} 4K:${V}${up_done}${R}↓${V}${dl_count}${R} TTS:${V}${tts_count}${R} Q:${queue}"
