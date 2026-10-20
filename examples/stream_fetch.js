// Run in the browser console on the local /docs page, with offline Mock configuration.
// POST streaming uses fetch: EventSource cannot send a messages body.
const response = await fetch('/v1/chat/stream', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ model: 'mock-echo', messages: [{ role: 'user', content: 'Hello Gateway' }] }),
});
if (!response.ok) throw new Error(`Gateway HTTP ${response.status}`);
const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
try {
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    console.log(value); // Network chunks can contain partial or multiple SSE events.
  }
} finally {
  await reader.cancel();
  reader.releaseLock();
}
