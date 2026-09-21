import test from "node:test";
import assert from "node:assert/strict";
import { strategy2ServerStatus } from "../lib/aster-strategy2-server-status.mjs";

test("newer server config supersedes stale confirmed mutation state", () => {
  const server = { configVersion: 42, settings: { version: 42, entrySizingMode: "margin" } };
  const staleConfirmed = { configVersion: 41, settings: { version: 41, entrySizingMode: "notional" } };
  const status = strategy2ServerStatus(server, staleConfirmed, true);
  assert.equal(status.state, server);
  assert.equal(status.state.settings.entrySizingMode, "margin");
});

test("same-or-newer confirmed mutation remains authoritative until server catches up", () => {
  const server = { configVersion: 42, settings: { version: 42, entrySizingMode: "margin" } };
  const confirmed = { configVersion: 43, settings: { version: 43, entrySizingMode: "notional" } };
  const status = strategy2ServerStatus(server, confirmed, true);
  assert.equal(status.state, confirmed);
  assert.equal(status.state.settings.entrySizingMode, "notional");
});
