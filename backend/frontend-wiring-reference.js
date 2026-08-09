/**
 * Live Intake wiring — drop into the Live Intake screen's component.
 * Framework-agnostic vanilla JS; wrap the three callbacks in setState calls
 * if you're in React.
 *
 * WS_BASE must be wss:// once the frontend is served over https (which it
 * will be on the native.builder preview URL) — browsers block plain ws://
 * calls from an https page (mixed-content policy). Any host with automatic
 * TLS (Railway, Render, Fly) gives you this for free on their subdomain.
 */
const WS_BASE = "wss://your-backend-host.example.com";

async function startIntake(claimId, { onTranscript, onFields, onDossier }) {
  const ws = new WebSocket(`${WS_BASE}/ws/intake/${claimId}`);
  ws.binaryType = "arraybuffer";

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === "transcript") onTranscript(msg.speaker, msg.text, msg.is_final);
    else if (msg.type === "fields") onFields(msg.fields);
    else if (msg.type === "dossier") onDossier(msg.dossier);
  };

  await new Promise((resolve, reject) => {
    ws.onopen = resolve;
    ws.onerror = reject;
  });

  // Web Audio API, not MediaRecorder — we need raw PCM16, not WebM/Opus.
  // Some browsers don't fully honor the requested sampleRate; if transcription
  // quality looks off, log audioContext.sampleRate and add a resample step.
  const audioContext = new AudioContext({ sampleRate: 16000 });
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const source = audioContext.createMediaStreamSource(stream);

  // ScriptProcessorNode is deprecated but simplest for now; AudioWorkletNode
  // is the modern replacement if there's time to switch later.
  const processor = audioContext.createScriptProcessor(4096, 1, 1);

  processor.onaudioprocess = (e) => {
    if (ws.readyState !== WebSocket.OPEN) return;
    const float32 = e.inputBuffer.getChannelData(0);
    const int16 = new Int16Array(float32.length);
    for (let i = 0; i < float32.length; i++) {
      const s = Math.max(-1, Math.min(1, float32[i]));
      int16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    ws.send(int16.buffer); // binary WebSocket frame -> backend -> Speechmatics
  };

  // ScriptProcessorNode only fires onaudioprocess while connected to a sink,
  // but that sink must NOT be audible — connecting straight to destination
  // pipes the mic back out of the speakers and howls with feedback the
  // moment intake starts. Route through a silent gain node instead.
  const mute = audioContext.createGain();
  mute.gain.value = 0;

  source.connect(processor);
  processor.connect(mute);
  mute.connect(audioContext.destination);

  return {
    endCall: () => {
      ws.send(JSON.stringify({ type: "end_call" })); // triggers stages 3+4 server-side
      processor.disconnect();
      source.disconnect();
      stream.getTracks().forEach((t) => t.stop());
    },
  };
}

// Usage in the Live Intake screen:
//
// const session = await startIntake(claimId, {
//   onTranscript: (speaker, text, isFinal) => { /* append to transcript state */ },
//   onFields: (fields) => { /* update extracted-fields panel state */ },
//   onDossier: (dossier) => { /* call ended — navigate to Verdict/Dossier screen */ },
// });
//
// // on "End call" button click:
// session.endCall();
