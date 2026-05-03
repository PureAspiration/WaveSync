# WaveSync

**WaveSync** automatically synchronises a long ambient audio recording (e.g. from a headset or recorder) with one or more video files recorded at the same time, then merges them into polished MP4s with the recording mixed in.

It works by searching for the recording start time in the video and audio metadata for an estimated offset and then
cross-correlating the waveforms from both sources to find the exact time offset.

---

## Why did I make this?

I was flying a light general aviation aircraft and recording flight cockpit audio with my headset connected to voice recorder on my phone, recording the entire duration of my flight. Any videos I took with my Meta glasses would not have this audio synced to it and all I could hear was the engine sound.

Other alternatives either cost quite a lot or are unable to match effectively with the loud engine drone noise.

WaveSync solves this by:
1. Reading the **creation timestamps** from each video file's EXIF data to get a rough offset.
2. Extracting a short audio window from both sources around that rough offset.
3. Running **cross-correlation** on the high pass filtered waveforms to cut through engine noise and find the *exact* offset to millisecond precision.
4. Merging the audio and video files with `ffmpeg`, mixing the recording in at full volume and the original camera audio at 30% (adjustable).

---

## Requirements

### System tools

| Tool                                | Purpose                                                                                           |
|-------------------------------------|---------------------------------------------------------------------------------------------------|
| [`ffmpeg`](https://ffmpeg.org/)     | Audio/video extraction and merging                                                                |
| [`ffprobe`](https://ffmpeg.org/)    | Reading video duration (bundled with ffmpeg)                                                      |
| [`exiftool`](https://exiftool.org/) | Reading EXIF creation timestamps and copying metadata                                             |
| `powershell`                        | Copying filesystem timestamps (Windows only). Not really required... just remove it from the code |

### Python dependencies

```
numpy
scipy
matplotlib
```

Install with:

```bash
pip install numpy scipy matplotlib
```

Python 3.8+ is required.

---

## Project structure

```
project/
├── main.py            # The code...
├── audio.m4a          # Long ambient audio recording
└── videos/
    ├── clip1.mp4
    ├── clip2.mp4
    └── ...
```

Output is written to:

```
project/
├── processing_output/               # Intermediate WAVs and debug plots
│   ├── video_audio.wav
│   ├── headset_audio.wav
│   ├── waveform_comparison.png
│   └── correlation_peak.png
└── output/                          # Final merged video files
    ├── clip1_merged.mp4
    └── clip2_merged.mp4
```

---

## Configuration

At the top of `main.py`, adjust these variables before running:

```python
AUDIO_FILE = "audio.m4a"   # Path to your long ambient recording
AUDIO_START_TIME = "2026:04:30 23:32:40Z"     # Recording start time (EXIF format, UTC)
 # AUDIO_START_TIME can also be set to None to automatically determine using exiftool

VIDEO_FOLDER = "videos"                        # Folder containing your video clips

AUDIO_WINDOW = 30    # Seconds either side of the rough offset to search (increase if timestamps are unreliable)
SHOW_SECS    = 60    # Seconds of video audio used for correlation (longer = more reliable but slower)
```

### Getting `AUDIO_START_TIME`

Run `exiftool` on your audio file to find the creation timestamp:

```bash
exiftool -s3 -CreationDate "audio.m4a"
```

The format used is `YYYY:MM:DD HH:MM:SSZ` (UTC).

---

## How it works

```
Actual video start time = /

FULL AUDIO FILE          |-----------------------------------------------------------------|            
FULL VIDEO FILE                              /-------------------------------|
                         <-- Actual offset -->
                                             <---> Offset discrepancy

                         <---- Rough offset ---->|          This will vary the audio extract position. 
AUDIO EXTRACT                       |--------/---|-------------------|------------|
                                    |<- Window ->|<--- SHOW_SECS --->|<- Window ->|

VIDEO EXTRACT                                /-------------------|
                                             0               SHOW_SECS
                                             (always from start of video file)
Ideally the video extract should be within the audio extract range.
```

For each video file:

1. **Rough offset** is calculated from the difference between `AUDIO_START_TIME` and the video's EXIF `CreationDate`.
2. **Audio extraction** — a `SHOW_SECS` length clip is extracted from the video, and a corresponding window (`rough_offset ± AUDIO_WINDOW + SHOW_SECS`) is extracted from the recording.
3. **Filtering** — a 300 Hz high-pass Butterworth filter is applied to both clips to remove low-frequency rumble (engine noise, wind, etc.), then both are peak-normalised.
4. **Cross-correlation** — `scipy.signal.correlate` finds the lag that maximises alignment between the two waveforms.
5. **Confidence score** — the ratio of the correlation peak to the mean is reported. A high score (e.g. 10×+) indicates a reliable match. A low score may mean there's not enough audio detail in the clip.
6. **Merge** — `ffmpeg` combines the video with the recording, offset by the calculated value, mixing audio from both sources.

---

## Running

```bash
python main.py
```

WaveSync will iterate through every `.mp4`, `.mov`, and `.avi` file in the `videos/` folder and process each one in turn.

During the merge step you will be prompted:

```
Padding before/after video (e.g. 30s, 2m, 1m30s) [default: 0]:
```

Padding adds black frames and recording audio before and after the video clip. Useful if you want context around a highlight. Press Enter to skip.

---

## Debug plots

After correlation, WaveSync saves two plots to `processing_output/`:

**`waveform_comparison.png`** — Visual comparison of the video and recording audio waveforms, and an overlay to manually verify alignment.

**`correlation_peak.png`** — The cross-correlation curve, with the detected peak marked. A sharp, isolated peak indicates high confidence. A flat or noisy curve suggests the two clips don't share enough audio features.

You can also uncomment `plot_waveforms(...)` in `process_video()` to display the waveform plot interactively.

---

## Output files

Each merged video is saved to `output/<original_filename>_merged.mp4`.

- Video stream: copied as-is (no re-encode) when no padding is used; re-encoded with `libx264` when padding is applied.
- Audio: the recording is mixed at **100%** volume; original camera audio is mixed at **30%**.
- EXIF metadata (including creation timestamp) is copied from the original video file to the merged output.
- On Windows, filesystem timestamps (`CreationTime`, `LastWriteTime`, `LastAccessTime`) are also copied via PowerShell.

---

## Troubleshooting

| Problem | Likely cause | Fix |
|---------|-------------|-----|
| Low confidence score | Clip has little audio variation, or the offset window is wrong | Increase `AUDIO_WINDOW`, or verify `AUDIO_START_TIME` |
| `exiftool` returns no date | Video has no EXIF creation metadata | Set `rough_offset` manually in `process_video()` |
| ffmpeg merge fails | Offset is negative (recording started after video) | Check that `AUDIO_START_TIME` is correct and in UTC |
| Waveforms look aligned but output is off | Sample rate mismatch | Both streams are resampled to 16 kHz — check `load_wav()` output |
| PowerShell errors on non-Windows | `copy_metadata()` calls PowerShell | Remove the PowerShell block in `copy_metadata()` if not on Windows |

---

## Platform notes

WaveSync was developed on **Windows**. The `copy_metadata()` function uses PowerShell to mirror filesystem timestamps and will fail on macOS/Linux. To use on other platforms, remove or replace the PowerShell block at the bottom of `copy_metadata()` — the `exiftool` step above it is cross-platform.

---

## License

MIT — do whatever you like with it.