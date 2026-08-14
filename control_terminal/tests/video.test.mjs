import assert from "node:assert/strict";
import test from "node:test";

import { resolveVideoEndpoint } from "../src/video.js";

test("video endpoint follows control host and websocket security", () => {
  assert.equal(
    resolveVideoEndpoint("ws://192.168.0.108:8765/ws", "/video"),
    "ws://192.168.0.108:8765/video",
  );
  assert.equal(
    resolveVideoEndpoint("wss://rover.example/ws", "/video"),
    "wss://rover.example/video",
  );
});
