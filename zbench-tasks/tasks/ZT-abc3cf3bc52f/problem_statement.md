# Open YouTube videos at the correct timestamp in the lightbox

## Background

In the Zulip web app, when a message contains a link to a YouTube video, the message body shows a video preview thumbnail. Clicking the thumbnail opens the video in Zulip's lightbox media viewer, which embeds the video in an iframe so it can be played without leaving the app.

## Current behavior

When the linked YouTube URL specifies a start time (for example `https://youtu.be/VIDEO_ID?t=120` or `https://www.youtube.com/watch?v=VIDEO_ID&t=1h30m`), the lightbox ignores it: the embedded player always starts playback at the beginning of the video.

## Required behavior

When a YouTube link includes a start-time offset, the lightbox must open the embedded video at that offset. Links without a start time must continue to open at the beginning of the video, exactly as today.

Both YouTube URL styles must be supported:

- Short links: `https://youtu.be/VIDEO_ID?t=...`
- Watch links: `https://www.youtube.com/watch?v=VIDEO_ID&t=...`

The start time may be expressed in either of the query parameters YouTube uses:

- `t` — the primary parameter.
- `start` — used as a fallback when `t` is absent (e.g. `https://www.youtube.com/watch?v=VIDEO_ID&start=100` starts at 100 seconds).

The parameter value may be in either of two formats:

1. **Plain integer seconds**: `t=120` means 120 seconds.
2. **Duration format** `#h#m#s`, where each of the hours/minutes/seconds components is optional but they appear in that order: `t=1h` → 3600 seconds, `t=1m1s` → 61 seconds, `t=1h1m1s` → 3661 seconds, `t=1h30m` → 5400 seconds, `t=1m` → 60 seconds.

If the value matches neither format (e.g. `t=invalid`), it must be treated the same as no start time at all: the video opens at the beginning.

When a valid start time is found, the embed URL used for the lightbox iframe must be constructed so the YouTube embedded player begins playback at that offset (the YouTube embed API accepts a start offset in whole seconds via its `start` query parameter).

## Interface requirements

- The `web/src/util` module must export a function `parse_youtube_start_time(url: string): number | undefined` that extracts the start-time offset, in whole seconds, from a YouTube URL. It must handle both youtu.be short links and youtube.com/watch links.
- The function reads the `t` query parameter, falling back to the `start` query parameter if `t` is absent.
- A plain integer value (e.g. `t=120`) is returned as that number of seconds (`120`).
- A duration-formatted value of the form `#h#m#s` with each component optional (e.g. `1h1m1s`, `1h30m`, `1m`) is converted to total seconds (`3661`, `5400`, `60` respectively).
- If the URL has neither parameter, or the value matches neither the integer nor the duration format (e.g. `t=invalid`), the function returns `undefined`.

The lightbox video-embedding code must use this function so that the behavior described above is what users observe when opening YouTube previews.
