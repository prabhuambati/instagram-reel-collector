# Public Instagram Reel Music Collector (Prototype)

A local-first prototype for collecting public Instagram reel metadata, flagging likely human singing/instrument performances, extracting MP3 audio when FFmpeg is available, embedding creator attribution, detecting duplicates, and browsing the collection locally.

## What this prototype does

- Imports reel records exported by the browser extension or a JSON/CSV file.
- Stores username, profile URL, profile-photo URL, public ID when available, reel URL, caption, and search source.
- Uses a transparent heuristic classifier for an initial review queue. It does **not** pretend to be a production-grade vision/audio model yet.
- Tracks duplicate reel URLs and content hashes.
- Converts video to MP3 with FFmpeg when installed.
- Embeds title, artist/creator, album, and original reel URL into the MP3 metadata.
- Serves a searchable local dashboard.
- Exports credits as CSV and JSON.

## Important boundaries

Use it only for public content that you are permitted to collect. It does not bypass login walls, CAPTCHAs, rate limits, private accounts, or Instagram access controls. Keep the collection private unless you have the necessary rights to redistribute audio or images. Attribution is included, but attribution alone does not grant copyright permission.

## Run

```bash
cd instagram_reel_collector
python3 run.py init
python3 run.py serve
```

Open http://127.0.0.1:8765.

Import an exported JSON file from the dashboard, or use the CLI:

```bash
python3 run.py import-json ./sample_records.json --source-kind hashtag --source-query '#coversong'
python3 run.py export --format csv --output data/exports/credits.csv
python3 run.py export --format json --output data/exports/credits.json
```

To process a downloaded video and create an attributed MP3:

```bash
python3 run.py process-video ./video.mp4 --reel-url 'https://www.instagram.com/reel/...' --username creator_name
```

A project-local FFmpeg bundle is installed under `.vendor/` for MP3 conversion. The converter uses a system `ffmpeg` first and falls back to that local bundle. Metadata-only imports still work without FFmpeg.

## Browser extension

The `extension/` folder is a small Manifest V3 extension. Load it unpacked in Chrome/Chromium, open a public Instagram search/profile page, and click **Collect visible reels** after each page or scroll segment. It collects links and visible public metadata only; it does not bypass access controls or automatically evade anti-bot systems. Use the popup's **Download JSON** button, then import that file into the local dashboard.

## Next production upgrades

1. Replace the heuristic classifier with a multimodal classifier and a review threshold.
2. Add a licensed audio-fingerprint provider for song recognition.
3. Add a browser-controlled discovery runner with an explicit per-source cap and pause/review controls.
4. Add resumable jobs, rate-limit backoff, and audit logs.
5. Add a permission-aware policy screen before bulk collection.
