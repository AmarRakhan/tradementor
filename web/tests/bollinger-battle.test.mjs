import test from 'node:test';
import assert from 'node:assert/strict';
import {
  battleStatus,
  bollingerScore,
  clampBollingerScore,
  legacyPressureOverrideToBollingerScore,
  scoreToTimelineTime,
  shouldAnimateScore,
  timeframeToAsterInterval,
  transitionDurationMs,
} from '../lib/bollinger-battle.mjs';

test('maps canonical Bollinger positions 0..100', () => {
  for (const expected of [0, 1, 10, 25, 49, 50, 51, 75, 90, 99, 100]) {
    const price = 100 + expected;
    assert.equal(bollingerScore(price, 100, 200), expected);
  }
});

test('clamps prices outside the bands and rejects invalid bands', () => {
  assert.equal(bollingerScore(90, 100, 200), 0);
  assert.equal(bollingerScore(210, 100, 200), 100);
  assert.equal(bollingerScore(150, 200, 100), null);
  assert.equal(bollingerScore(Number.NaN, 100, 200), null);
  assert.equal(clampBollingerScore(Number.NaN), 50);
});

test('maps the UI timeframes to the canonical Aster intervals', () => {
  assert.equal(timeframeToAsterInterval('1m'), '1m');
  assert.equal(timeframeToAsterInterval('5m'), '5m');
  assert.equal(timeframeToAsterInterval('15m'), '15m');
  assert.equal(timeframeToAsterInterval('1h'), '1h');
  assert.equal(timeframeToAsterInterval('4h'), '4h');
  assert.equal(timeframeToAsterInterval('24h'), '1d');
});

test('maps 0, 50 and 100 to the exact video timeline anchors', () => {
  assert.equal(scoreToTimelineTime(0, 12), 0);
  assert.equal(scoreToTimelineTime(50, 12), 6);
  assert.equal(scoreToTimelineTime(100, 12), 12);
  assert.equal(scoreToTimelineTime(75, 12), 9);
});

test('smoothing uses a small deadband and bounded transition duration', () => {
  assert.equal(shouldAnimateScore(50, 50.2), false);
  assert.equal(shouldAnimateScore(50, 51), true);
  assert.equal(transitionDurationMs(50, 51), 329);
  assert.equal(transitionDurationMs(0, 100), 850);
});

test('status and legacy test override remain deterministic', () => {
  assert.equal(battleStatus(48), 'SHORTS DRUKKEN HARDER');
  assert.equal(battleStatus(50), 'IN EVENWICHT');
  assert.equal(battleStatus(52), 'LONGS DRUKKEN HARDER');
  assert.equal(legacyPressureOverrideToBollingerScore(-100), 0);
  assert.equal(legacyPressureOverrideToBollingerScore(0), 50);
  assert.equal(legacyPressureOverrideToBollingerScore(100), 100);
});
