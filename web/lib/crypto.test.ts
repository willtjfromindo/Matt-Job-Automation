// Run with: npm test   (uses Node's built-in test runner and type stripping)
import { test } from "node:test";
import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import { decrypt, encrypt } from "./crypto.ts";

const key = randomBytes(32).toString("base64");

test("round-trips a refresh token", () => {
  const token = "1//0gExampleRefreshToken-abc_123";
  const stored = encrypt(token, key);
  assert.equal(decrypt(stored, key), token);
});

test("layout is iv(12) || ciphertext || tag(16), base64", () => {
  const plaintext = "hello";
  const raw = Buffer.from(encrypt(plaintext, key), "base64");
  assert.equal(raw.length, 12 + Buffer.byteLength(plaintext) + 16);
});

test("uses a fresh IV every time", () => {
  assert.notEqual(encrypt("same", key), encrypt("same", key));
});

test("rejects tampered data", () => {
  const raw = Buffer.from(encrypt("secret", key), "base64");
  raw[14] ^= 0xff;
  assert.throws(() => decrypt(raw.toString("base64"), key));
});

test("rejects the wrong key", () => {
  const stored = encrypt("secret", key);
  assert.throws(() => decrypt(stored, randomBytes(32).toString("base64")));
});

test("requires a 32-byte key", () => {
  assert.throws(() => encrypt("x", randomBytes(16).toString("base64")), /32 bytes/);
  assert.throws(() => encrypt("x", ""), /not set/);
});
