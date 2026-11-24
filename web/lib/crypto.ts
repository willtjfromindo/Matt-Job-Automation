// Refresh-token encryption shared with the Python worker.
//
// Format (must match the worker exactly):
//   key    = base64-decode(TOKEN_ENCRYPTION_KEY)  -> exactly 32 bytes (AES-256)
//   stored = base64( iv (12 bytes) || ciphertext || authTag (16 bytes) )
//
// Python side:
//   raw = base64.b64decode(stored)
//   AESGCM(key).decrypt(raw[:12], raw[12:], None)
//
// No imports beyond node:crypto so `node --test` can run it directly.
import { createCipheriv, createDecipheriv, randomBytes } from "node:crypto";

const IV_BYTES = 12;
const TAG_BYTES = 16;

export function encryptionKey(keyBase64: string | undefined = process.env.TOKEN_ENCRYPTION_KEY): Buffer {
  if (!keyBase64 || !keyBase64.trim()) {
    throw new Error("TOKEN_ENCRYPTION_KEY is not set");
  }
  const key = Buffer.from(keyBase64.trim(), "base64");
  if (key.length !== 32) {
    throw new Error(`TOKEN_ENCRYPTION_KEY must be base64 of exactly 32 bytes (got ${key.length})`);
  }
  return key;
}

export function encrypt(plaintext: string, keyBase64?: string): string {
  const iv = randomBytes(IV_BYTES);
  const cipher = createCipheriv("aes-256-gcm", encryptionKey(keyBase64), iv, { authTagLength: TAG_BYTES });
  const ciphertext = Buffer.concat([cipher.update(plaintext, "utf8"), cipher.final()]);
  const tag = cipher.getAuthTag();
  return Buffer.concat([iv, ciphertext, tag]).toString("base64");
}

export function decrypt(stored: string, keyBase64?: string): string {
  const raw = Buffer.from(stored, "base64");
  if (raw.length < IV_BYTES + TAG_BYTES) {
    throw new Error("Encrypted value is too short");
  }
  const iv = raw.subarray(0, IV_BYTES);
  const tag = raw.subarray(raw.length - TAG_BYTES);
  const ciphertext = raw.subarray(IV_BYTES, raw.length - TAG_BYTES);
  const decipher = createDecipheriv("aes-256-gcm", encryptionKey(keyBase64), iv, { authTagLength: TAG_BYTES });
  decipher.setAuthTag(tag);
  return Buffer.concat([decipher.update(ciphertext), decipher.final()]).toString("utf8");
}
