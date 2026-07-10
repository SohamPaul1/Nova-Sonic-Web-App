# Graph Report - .  (2026-07-09)

## Corpus Check
- 3 files · ~7,180 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 104 nodes · 171 edges · 12 communities (6 shown, 6 thin omitted)
- Extraction: 97% EXTRACTED · 3% INFERRED · 0% AMBIGUOUS · INFERRED: 5 edges (avg confidence: 0.8)
- Token cost: 42,000 input · 3,300 output

## Community Hubs (Navigation)
- Bedrock Stream Manager & Events
- Frontend Audio & VAD Barge-in
- Server Core & Response Loop
- Synced Transcript Reveal
- Tool Processor
- Async Tool Request Handling
- Friend System Prompt
- FastAPI Dependency
- Smithy AWS Core Dependency
- Uvicorn Server
- WebSockets Dependency
- Mute Toggle

## God Nodes (most connected - your core abstractions)
1. `BedrockStreamManager` - 24 edges
2. `debug_print()` - 20 edges
3. `handleServerMessage` - 9 edges
4. `websocket_endpoint()` - 8 edges
5. `startStreaming` - 8 edges
6. `onLocalSpeechStart` - 7 edges
7. `revealTick` - 7 edges
8. `endAssistantSegment` - 6 edges
9. `ToolProcessor` - 5 edges
10. `stopStreaming` - 5 edges

## Surprising Connections (you probably didn't know these)
- `Friend System Prompt` --conceptually_related_to--> `aws_sdk_bedrock_runtime`  [INFERRED]
  prompt.txt → requirements.txt

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Synced transcript reveal pipeline** — static_index_bufferassistanttext, static_index_ensureassistantsegment, static_index_revealtick, static_index_endassistantsegment, static_index_flushsegment [EXTRACTED 0.90]
- **Neural VAD barge-in and audio suppression** — static_index_startvad, static_index_onlocalspeechstart, static_index_clearplayback, static_index_playaudiochunk, static_index_releaseaudiosuppression [EXTRACTED 0.90]
- **Audio-clock progress interpolation** — static_index_playaudiochunk, static_index_revealtick, static_index_audio_clock_interpolation [INFERRED 0.85]

## Communities (12 total, 6 thin omitted)

### Community 0 - "Bedrock Stream Manager & Events"
Cohesion: 0.14
Nodes (13): BedrockStreamManager, Manages bidirectional streaming with AWS Bedrock using asyncio, Create a tool result event, Send a raw event JSON to the Bedrock stream., Send a content start event to the Bedrock stream., Add an audio chunk to the queue., Send a content end event to the Bedrock stream., Send a tool content start event to the Bedrock stream. (+5 more)

### Community 1 - "Frontend Audio & VAD Barge-in"
Cohesion: 0.13
Nodes (23): addTranscriptMessage, Audio capture and PCM streaming, Barge-in interruption mechanism, cleanupAudio, clearPlayback, downsample, Echo-cancelled shared-stream VAD gating, endAssistantSegment (+15 more)

### Community 2 - "Server Core & Response Loop"
Cohesion: 0.13
Nodes (15): debug_print(), get_current_time_str(), get_index(), Create a promptStart event, Initialize the Bedrock client., Initialize the bidirectional stream with Bedrock., Print only if debug mode is enabled, Process audio input from the queue and send to Bedrock. (+7 more)

### Community 3 - "Synced Transcript Reveal"
Cohesion: 0.20
Nodes (14): assistantSegment (reveal state), Audio-clock progress interpolation, In-flight audio suppression, bufferAssistantText, clamp01, ensureAssistantSegment, flushSegment, Gapless nextPlayTime scheduling (+6 more)

### Community 4 - "Tool Processor"
Cohesion: 0.29
Nodes (4): Initialize the stream manager., Process a tool call asynchronously and return the result, Internal method to execute the tool logic, ToolProcessor

### Community 6 - "Friend System Prompt"
Cohesion: 0.67
Nodes (3): Order Number Digit-Reading Convention, Friend System Prompt, aws_sdk_bedrock_runtime

## Knowledge Gaps
- **11 isolated node(s):** `FastAPI`, `Uvicorn`, `websockets`, `aws_sdk_bedrock_runtime`, `smithy-aws-core` (+6 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **6 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `BedrockStreamManager` connect `Bedrock Stream Manager & Events` to `Server Core & Response Loop`, `Tool Processor`, `Async Tool Request Handling`?**
  _High betweenness centrality (0.147) - this node is a cross-community bridge._
- **Why does `debug_print()` connect `Server Core & Response Loop` to `Bedrock Stream Manager & Events`, `Tool Processor`, `Async Tool Request Handling`?**
  _High betweenness centrality (0.081) - this node is a cross-community bridge._
- **Why does `handleServerMessage` connect `Frontend Audio & VAD Barge-in` to `Synced Transcript Reveal`?**
  _High betweenness centrality (0.052) - this node is a cross-community bridge._
- **What connects `Order Number Digit-Reading Convention`, `FastAPI`, `Uvicorn` to the rest of the system?**
  _38 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Bedrock Stream Manager & Events` be split into smaller, more focused modules?**
  _Cohesion score 0.13538461538461538 - nodes in this community are weakly interconnected._
- **Should `Frontend Audio & VAD Barge-in` be split into smaller, more focused modules?**
  _Cohesion score 0.13438735177865613 - nodes in this community are weakly interconnected._
- **Should `Server Core & Response Loop` be split into smaller, more focused modules?**
  _Cohesion score 0.13333333333333333 - nodes in this community are weakly interconnected._