import os
import subprocess
from datetime import datetime

import matplotlib.pyplot as plt
import numpy as np
from scipy.io import wavfile
from scipy.signal import correlate, butter, filtfilt


# ── Configuration ─────────────────────────────────────────────────────────────

AUDIO_FILE = "audio.m4a"
AUDIO_START_TIME = None
# AUDIO_START_TIME = "2026:04:30 23:32:40Z"

VIDEO_FOLDER = "videos"

AUDIO_WINDOW = 30  # seconds either side to attempt match
SHOW_SECS = 60  # Amount of audio data to use from video (starts from beginning of video)

# DETERMINED AUTOMATICALLY
# rough_offset = 2770  # best guess of video offset in seconds

"""
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
"""


# ── Extract ───────────────────────────────────────────────────────────────────
def extract_audio(input_path, output_path, start_sec=None, duration_sec=None):
    cmd = ["ffmpeg", "-y"]
    if start_sec is not None:
        cmd += ["-ss", str(start_sec)]
    cmd += ["-i", input_path]
    if duration_sec is not None:
        cmd += ["-t", str(duration_sec)]
    cmd += ["-ac", "1", "-ar", "16000", "-vn", output_path]
    subprocess.run(cmd, check=True, capture_output=True)


def load_wav(path):
    rate, data = wavfile.read(path)
    audio = data.astype(np.float32) / np.iinfo(data.dtype).max
    return rate, audio


def get_audio_segments(video_path, rough_offset):
    audio_window_min = rough_offset - AUDIO_WINDOW
    audio_window_max = rough_offset + SHOW_SECS + AUDIO_WINDOW
    audio_extract_duration = audio_window_max - audio_window_min

    os.makedirs("processing_output", exist_ok=True)
    extract_audio(video_path, "processing_output/video_audio.wav", duration_sec=SHOW_SECS)
    extract_audio(AUDIO_FILE, "processing_output/headset_audio.wav",
                  start_sec=max(0, audio_window_min),
                  duration_sec=audio_extract_duration)

    rate_v, v_raw = load_wav("processing_output/video_audio.wav")
    rate_h, h_raw = load_wav("processing_output/headset_audio.wav")

    # High-pass both waves
    v_clean = normalize(highpass(v_raw, rate_v, cutoff=300))
    h_clean = normalize(highpass(h_raw, rate_h, cutoff=300))

    return rate_v, rate_h, v_clean, h_clean, audio_window_min, audio_extract_duration


def get_creation_date(filepath):
    return subprocess.run(
        ["exiftool", "-s3", "-CreationDate", filepath],
        capture_output=True,
        text=True
    ).stdout.strip()


def parse_duration(s):
    """Parse a duration string like 30s, 2m, 1m30s into seconds."""
    import re
    s = s.strip().lower()
    match = re.fullmatch(r'(?:(\d+)m)?(?:(\d+)s?)?', s)
    if not match or not any(match.groups()):
        raise ValueError(f"Unrecognised duration format: '{s}'. Use e.g. 30s, 2m, 1m30s")
    minutes = int(match.group(1) or 0)
    seconds = int(match.group(2) or 0)
    return minutes * 60 + seconds


# ── Audio Clean up ────────────────────────────────────────────────────────────
def highpass(data, rate, cutoff=300):
    """Remove low-frequency rumble (engine drone)"""
    coef = butter(4, cutoff / (rate / 2), btype="high")
    b, a = coef[0], coef[1]
    return filtfilt(b, a, data)


def normalize(data):
    """Scale to ±1.0 based on peak"""
    peak = np.max(np.abs(data))
    return data / peak if peak > 0 else data


# ── Processing ────────────────────────────────────────────────────────────────
def find_offset_filtered(v_clean, h_clean, rate, rough_offset, window):
    """Run correlation on the filtered/normalized arrays you already have"""

    # Use only the first 60s of video audio for speed
    v_seg = v_clean[:rate * 60]

    # Correlate
    correlation: np.ndarray = correlate(h_clean, v_seg, mode="valid")
    lag = np.argmax(np.abs(correlation))
    offset_seconds = (rough_offset - window) + (lag / rate)

    peak = np.max(np.abs(correlation))
    noise = np.mean(np.abs(correlation))
    confidence = peak / noise

    return offset_seconds, confidence, correlation, lag, rate, peak


# ── Plot ──────────────────────────────────────────────────────────────────────
def plot_waveforms(v_clean, h_clean, rate_h, audio_window_min, audio_extract_duration):
    # Clip audio to ±0.5, so it doesn't visually dominate
    h_display = np.clip(h_clean, -0.5, 0.5)

    time_v = np.linspace(0, SHOW_SECS, len(v_clean))
    time_h = np.linspace(0, audio_extract_duration, len(h_clean))

    fig, axes = plt.subplots(3, 1, figsize=(14, 8))
    fig.suptitle("Cleaned Waveform Comparison", fontsize=13)

    # Video waveform
    axes[0].plot(time_v, v_clean, linewidth=0.3, color="#e05c3a")
    axes[0].set_title("Video audio — high-pass filtered")
    axes[0].set_ylabel("Amplitude")
    axes[0].set_ylim(-1, 1)

    # Recording waveform
    axes[1].plot(time_h, h_display, linewidth=0.3, color="#3a7ee0")
    axes[1].set_title(f"Recording audio — high-pass filtered (starting ~{audio_window_min}s)")
    axes[1].set_ylabel("Amplitude")
    axes[1].set_ylim(-0.5, 0.5)

    # Overlay
    h_offset_samples = AUDIO_WINDOW * rate_h
    h_overlay = h_display[h_offset_samples:h_offset_samples + len(v_clean)]
    axes[2].plot(time_v, v_clean, linewidth=0.4, color="#e05c3a", alpha=0.7, label="Video")
    axes[2].plot(time_v, h_overlay, linewidth=0.4, color="#3a7ee0", alpha=0.7, label="Recording")
    axes[2].set_title("Overlaid waveforms — align peaks to determine offset")
    axes[2].set_ylabel("Amplitude")
    axes[2].set_ylim(-1, 1)
    axes[2].legend()

    for ax in axes:
        ax.set_xlabel("Time (seconds)")
        ax.grid(True, alpha=0.2)

    plt.tight_layout()
    plt.savefig("processing_output/waveform_comparison.png", dpi=150)
    plt.show()


def plot_correlation(corr, lag, rate, offset, peak, rough_offset):
    fig, ax = plt.subplots(figsize=(12, 3))
    times = (np.arange(len(corr)) / rate) - AUDIO_WINDOW

    ax.plot(times, np.abs(corr), linewidth=0.5, color="#3a7ee0")
    ax.axvline(lag / rate - AUDIO_WINDOW, color="#e05c3a", linewidth=1.5,
               label=f"Peak of {round(peak)} at {offset:.3f}s")
    ax.set_title("Cross-correlation", fontweight="bold", pad=15)
    ax.set_xlabel("Time relative to rough offset (seconds)")
    ax.set_ylabel("Correlation")
    ax.legend()

    sec_ax = ax.secondary_xaxis("top", functions=(
        lambda x: x + rough_offset,
        lambda x: x - rough_offset
    ))
    sec_ax.set_xlabel("Time relative to recording (seconds)")

    plt.tight_layout()
    plt.savefig("processing_output/correlation_peak.png", dpi=150)
    plt.show()


# ── Main ──────────────────────────────────────────────────────────────────────
def process_video(video_path, audio_start_datetime):
    print("==============================")
    print(f"Processing: {video_path}")

    video_start_time = get_creation_date(video_path)
    video_start_datetime = datetime.strptime(video_start_time, "%Y:%m:%d %H:%M:%SZ")
    rough_offset = (video_start_datetime - audio_start_datetime).total_seconds()
    print(f"Rough offset: {rough_offset:.3f} seconds, {video_start_time} - {audio_start_datetime}")

    rate_v, rate_h, v_clean, h_clean, audio_window_min, audio_extract_duration = get_audio_segments(video_path, rough_offset)
    # plot_waveforms(v_clean, h_clean, rate_h, audio_window_min, audio_extract_duration)

    offset, confidence, corr, lag, rate, peak = find_offset_filtered(
        v_clean, h_clean, rate_v, rough_offset, AUDIO_WINDOW
    )
    print(f"Exact offset : {offset:.3f} seconds")
    print(f"Confidence   : {confidence:.1f}x")
    plot_correlation(corr, lag, rate_v, offset, peak, rough_offset)
    merge_audio_video(video_path, AUDIO_FILE, offset)


def merge_audio_video(video_path, audio_file, offset):
    os.makedirs("output", exist_ok=True)
    filename = os.path.splitext(os.path.basename(video_path))[0]
    output_path = f"output/{filename}_merged.mp4"

    padding_input = input("Padding before/after video (e.g. 30s, 2m, 1m30s) [default: 0]: ").strip()
    padding_secs = parse_duration(padding_input) if padding_input else 0
    print(f"Padding: {padding_secs}s")

    if padding_secs != 0:
        duration = float(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", video_path],
            capture_output=True, text=True
        ).stdout.strip())
        padded_duration = duration + padding_secs * 2
        audio_start = offset - padding_secs  # start recording audio padding_secs before video

        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,  # input 0: video (with its own audio)
            "-ss", str(audio_start), "-i", audio_file,  # input 1: recording, starting early
            "-filter_complex",
            # Pad video stream with black before/after
            f"[0:v]tpad=start_duration={padding_secs}:stop_duration={padding_secs}:color=black[v_out];"
            # Pad video audio with silence before/after to match black screen
            f"[0:a]adelay={padding_secs * 1000}|{padding_secs * 1000},apad=whole_dur={padded_duration}[a_video];"
            # Recording audio is already starting padding_secs early so no delay needed
            f"[1:a]volume=1.0,apad=whole_dur={padded_duration}[a_rec];"
            # Mix: video audio at 30%, recording at full
            "[a_video]volume=0.3[a_video_quiet];"
            "[a_video_quiet][a_rec]amix=inputs=2:duration=longest[a_out]",
            "-map", "[v_out]",
            "-map", "[a_out]",
            "-t", str(padded_duration),
            "-c:v", "libx264",
            "-progress", "pipe:1",
            output_path
        ]

    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-ss", str(offset), "-i", audio_file,
            "-filter_complex",
            "[0:a]volume=0.3[a_video];[a_video][1:a]amix=inputs=2:duration=first[a_out]",
            "-map", "0:v",
            "-map", "[a_out]",
            "-c:v", "copy",
            output_path
        ]

    subprocess.run(cmd, check=True)
    print(f"Saved: {output_path}")

    copy_metadata(video_path, output_path)
    print(f"Video processed: {output_path}")


def copy_metadata(input_path, output_path):
    input_full_path = os.path.abspath(input_path)
    output_full_path = os.path.abspath(output_path)

    print("Copying all exif data")
    subprocess.run(
        ["exiftool", f"-TagsFromFile={input_full_path}", "-all:all>all:all", output_full_path, "-overwrite_original"],
        check=True
    )

    for prop in ["CreationTime", "LastWriteTime", "LastAccessTime"]:
        print(f"Changing value {prop}")
        subprocess.run(
            ["powershell", "-Command",
             f"Set-ItemProperty -LiteralPath '{output_full_path}' -Name {prop} "
             f"-Value (Get-Item -LiteralPath '{input_full_path}').{prop}"],
            check=True
        )


def main():
    assert os.path.exists(VIDEO_FOLDER), f"Folder '{VIDEO_FOLDER}' does not exist"

    audio_start_time = AUDIO_START_TIME or get_creation_date(AUDIO_FILE)
    audio_start_datetime = datetime.strptime(audio_start_time, "%Y:%m:%d %H:%M:%SZ")

    VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi"}
    for filename in os.listdir(VIDEO_FOLDER):
        ext = os.path.splitext(filename)[1].lower()
        if ext not in VIDEO_EXTENSIONS:
            continue
        process_video(os.path.join(VIDEO_FOLDER, filename), audio_start_datetime)


if __name__ == "__main__":
    main()
