# Nova Sonic Web App

A real-time speech-to-speech web application built with Amazon Bedrock's Nova Sonic model and FastAPI.

This project converts the AWS sample console application into a modern web interface. Audio flows directly from the user's browser microphone through WebSockets to an EC2 server, which relays the stream to AWS Bedrock and sends the synthesized speech back to the browser.

## Features

- **Real-time Voice Conversation**: Full duplex speech-to-speech communication with the Amazon Nova Sonic model.
- **Modern Web Interface**: Premium dark-themed UI built with pure HTML/CSS/JS (no heavy frontend frameworks).
- **Live Transcripts**: Displays the ongoing conversation text as it happens.
- **Audio-Synced Transcript Reveal**: Nova Sonic sends the assistant's text far faster than its audio plays, so the raw transcript would appear seconds before the agent finishes speaking. Instead, assistant text is buffered and revealed **word-by-word, locked to the audio playback clock** ("progress-based interpolation"), so words surface in step with what's being spoken. User messages and typed input still render instantly.
- **Instant Barge-in (Neural VAD)**: Interrupt the assistant at any time. A client-side neural voice-activity detector (Silero, via [`@ricky0123/vad-web`](https://github.com/ricky0123/vad)) stops playback the moment *you* speak — with no server round-trip. It distinguishes human speech from background noise (fans, keyboard, music) and, because it reuses the browser's echo-cancelled mic stream, the assistant's own voice bleeding through the speakers won't trigger a false interruption. The server-side barge-in from Bedrock remains as an authoritative fallback.
- **Text-Only Chat (mute-safe)**: Mute the mic and type instead. While muted the VAD is paused and mic noise can no longer barge in, so text-only conversations aren't cut off or silenced mid-reply. Silent frames still keep the Bedrock stream warm so typed messages get a prompt response.
- **Digit-by-digit numbers**: The agent speaks phone numbers / PIN codes one digit at a time (written as hyphenated digits, e.g. `9-8-0-0-...`), while the on-screen transcript collapses them to the joined form (`9800...`). Display-only — the spoken audio is untouched.
- **Tool Integration**: Includes sample tools (Date/Time and Order Tracking) that the model can invoke to fetch real-time data.
- **Configurable Prompt**: The system prompt is loaded from a text file for easy customization without restarting the server.

## Architecture

```text
Browser (Client)                                EC2 Server (FastAPI)                          AWS Bedrock
┌────────────────────┐                          ┌────────────────────┐                        ┌────────────────────┐
│                    │     WebSocket (ws://)    │                    │     AWS SDK Stream     │                    │
│  Microphone        ├─────────────────────────►│  WebSocket Handler ├───────────────────────►│  Nova Sonic Model  │
│  (Web Audio API)   │   16kHz PCM (Int16)      │                    │     Bidirectional      │                    │
│                    │                          │                    │                        │                    │
│  Speaker           │◄─────────────────────────┤  Bedrock Relay     │◄───────────────────────┤  matthew voice     │
│  (Web Audio API)   │   24kHz PCM (Base64)     │                    │                        │                    │
└────────────────────┘                          └────────────────────┘                        └────────────────────┘
```

### Barge-in (interruption) flow

Barge-in is handled on two independent paths:

1. **Client-side (primary, instant)**: A neural VAD in the browser listens to the echo-cancelled microphone stream. When it classifies incoming audio as human speech, it stops playback locally in ~40–120 ms and suppresses any remaining audio from the interrupted turn (which the server keeps streaming until Bedrock catches up), so it can't resume playback.
2. **Server-side (authoritative fallback)**: Bedrock's own VAD emits an `interrupted` event, which the server relays to the client as a `barge_in` message. This lifts the client's audio suppression and confirms the interruption — and covers the case where the VAD model fails to load (the app degrades gracefully to server-only barge-in).

The VAD model (Silero) and its ONNX runtime are loaded from a CDN at runtime, so the first barge-in is only active after the model finishes downloading (look for `[VAD] neural VAD ready` in the browser console).

### Audio-synced transcript reveal

Bedrock streams the assistant's transcript text and its audio as **independent, uncorrelated** messages with no timing metadata — and the text arrives roughly 3× faster than the audio plays. To keep the transcript in step with the voice, the reveal is computed entirely on the client:

1. Incoming `assistant_text` is **buffered**, not rendered immediately. It's tokenized into words.
2. The first real (non-suppressed) audio chunk of a turn anchors a reveal clock. Using the Web Audio scheduler's own timeline (`playbackContext.currentTime` for the playback head and `nextPlayTime` for the end of all scheduled audio), a `requestAnimationFrame` loop maps playback progress → the number of words to show:

   ```text
   progress    = (currentTime - anchor) / (nextPlayTime - anchor)   // clamped 0..1
   wordsToShow = round(progress × totalBufferedWords)
   ```

   Because `nextPlayTime` grows as more audio arrives, the denominator grows too, which naturally holds the text back while the agent is still speaking. The revealed count is **monotonic** — it never regresses.
3. **On barge-in** (either path), the transcript **freezes at the last spoken word** and discards the unspoken remainder, so the visible text honestly reflects what was actually voiced.
4. **Fallback**: if buffered text never receives audio (e.g. a text-only reply or dropped audio), it drips in at a gentle fixed reading speed after a short timeout, so text is never left hidden.

This is entirely frontend logic (in `static/index.html`); the backend is unchanged. Reveal speed/fallback knobs are the `NO_AUDIO_FALLBACK_MS` and `FALLBACK_WPS` constants near the top of the page script.

## Prerequisites

- Python 3.12+
- AWS Account with Bedrock access to the `amazon.nova-2-sonic-v1:0` model.
- Valid AWS credentials with permissions to call `InvokeModelWithBidirectionalStream`.

## Setup Instructions

1. **Clone the repository and enter the directory**:
   ```bash
   cd Nova-Sonic-web-app
   ```

2. **Create and activate a virtual environment**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure Environment Variables**:
   Create a `.env` file in the root directory (or edit the existing one):
   ```env
   AWS_ACCESS_KEY_ID="your_access_key"
   AWS_SECRET_ACCESS_KEY="your_secret_key"
   AWS_DEFAULT_REGION="us-east-1"
   MODEL_ID="amazon.nova-2-sonic-v1:0"
   PORT=8009
   HOST=0.0.0.0
   ```

5. **Customize the System Prompt** (Optional):
   Edit `prompt.txt` to change how the assistant behaves.

## Running the Application

1. Activate the virtual environment:
   ```bash
   source .venv/bin/activate
   ```

2. Start the FastAPI server:
   ```bash
   python main.py
   ```
   *To enable detailed logging, use: `python main.py --debug`*

3. Access the web interface:
   Open your browser and navigate to the domain pointing to your server (e.g., `https://your-domain.com/`).

### Important Note on HTTPS and WebSockets

For the microphone to work in modern browsers, the site must be served over **HTTPS** (or `localhost`).

If you are using a reverse proxy (like Nginx) in front of the application, ensure it is configured to upgrade WebSocket connections. Example Nginx configuration:

```nginx
location / {
    proxy_pass http://127.0.0.1:8009;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}
```

## Troubleshooting

- **Microphone Access Denied**: Ensure you are accessing the site via HTTPS. Browsers block microphone access on unencrypted HTTP connections (except for `localhost`).
- **WebSocket Disconnected immediately**: Check your reverse proxy settings. The `Upgrade` and `Connection` headers must be passed to the backend.
- **Task was destroyed but it is pending / InvalidStateError**: These are known warnings from the underlying `awscrt` networking library when a client disconnects abruptly. They do not affect the stability of the application.
- **Barge-in feels delayed / doesn't stop on my voice**: Open the browser console and confirm you see `[VAD] neural VAD ready` after connecting. The Silero VAD model (~2 MB) plus its ONNX runtime are fetched from a CDN on first use, so instant barge-in only activates once that download completes. If you see `[VAD] failed to initialize...` (e.g. offline, CDN blocked, or a strict Content-Security-Policy), the app falls back to the slower server-side barge-in. To remove the CDN dependency, vendor the `onnxruntime-web` and `@ricky0123/vad-web` assets into `static/` and update the script/asset paths in `index.html`.
- **Agent gets cut off / silenced when typing with the mic muted**: This was caused by the neural VAD still listening to the live mic while muted and treating room noise/typing as a barge-in. Fixed by pausing the VAD on mute and guarding `onLocalSpeechStart` with `isMuted` in `static/index.html`. If it recurs, confirm muting flips `isMuted` and calls `micVAD.pause()`.
- **Transcript reveals slightly ahead of / behind the voice**: The transcript is paced by the Web Audio playback clock (see [Audio-synced transcript reveal](#audio-synced-transcript-reveal)). Small drift is expected since Bedrock provides no per-word timing. If text consistently lags or leads, adjust the reveal in `static/index.html` — the `revealTick()` progress mapping — and the `FALLBACK_WPS` / `NO_AUDIO_FALLBACK_MS` constants control the no-audio fallback drip.
