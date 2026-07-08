# Nova Sonic Web App

A real-time speech-to-speech web application built with Amazon Bedrock's Nova Sonic model and FastAPI.

This project converts the AWS sample console application into a modern web interface. Audio flows directly from the user's browser microphone through WebSockets to an EC2 server, which relays the stream to AWS Bedrock and sends the synthesized speech back to the browser.

## Features

- **Real-time Voice Conversation**: Full duplex speech-to-speech communication with the Amazon Nova Sonic model.
- **Modern Web Interface**: Premium dark-themed UI built with pure HTML/CSS/JS (no heavy frontend frameworks).
- **Live Transcripts**: Displays the ongoing conversation text as it happens.
- **Barge-in Support**: Interrupt the assistant at any time — playback stops immediately when you start speaking.
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
