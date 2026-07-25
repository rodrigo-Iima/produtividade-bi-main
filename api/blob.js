import { get, list, put } from '@vercel/blob';

const SNAPSHOT_PREFIX = 'okr/snapshots/';

function sendJson(response, body, status = 200) {
  const encoded = JSON.stringify(body);
  response.statusCode = status;
  response.setHeader('Content-Type', 'application/json; charset=utf-8');
  response.setHeader('Cache-Control', 'no-store, max-age=0');
  response.setHeader('Content-Length', Buffer.byteLength(encoded));
  response.end(encoded);
}

function isAuthorized(request) {
  const secret = process.env.CRON_SECRET;
  return Boolean(
    secret && request.headers?.authorization === `Bearer ${secret}`,
  );
}

function readJsonBody(request) {
  return new Promise((resolve, reject) => {
    let body = '';

    request.setEncoding('utf8');
    request.on('data', (chunk) => {
      body += chunk;
      if (Buffer.byteLength(body) > 10 * 1024 * 1024) {
        reject(new Error('request_body_too_large'));
        request.destroy();
      }
    });
    request.on('end', () => {
      try {
        resolve(body ? JSON.parse(body) : {});
      } catch {
        reject(new Error('invalid_json'));
      }
    });
    request.on('error', reject);
  });
}

async function readLatestSnapshot() {
  const { blobs } = await list({
    prefix: SNAPSHOT_PREFIX,
    limit: 1000,
  });

  if (!blobs.length) return null;

  const latest = [...blobs].sort((left, right) =>
    left.pathname.localeCompare(right.pathname),
  ).at(-1);
  const result = await get(latest.pathname, {
    access: 'private',
    useCache: false,
  });

  if (!result || result.statusCode !== 200 || !result.stream) return null;
  return new Response(result.stream).json();
}

export default async function handler(request, response) {
  if (!isAuthorized(request)) {
    sendJson(response, { error: 'unauthorized' }, 401);
    return;
  }

  try {
    if (request.method === 'GET') {
      const snapshot = await readLatestSnapshot();
      if (snapshot === null) {
        sendJson(response, { error: 'snapshot_not_found' }, 404);
        return;
      }
      sendJson(response, snapshot);
      return;
    }

    if (request.method === 'POST') {
      const body = await readJsonBody(request);
      const pathname = body?.pathname;
      const snapshot = body?.snapshot;

      if (
        typeof pathname !== 'string' ||
        !pathname.startsWith(SNAPSHOT_PREFIX) ||
        !snapshot ||
        typeof snapshot !== 'object' ||
        Array.isArray(snapshot)
      ) {
        sendJson(response, { error: 'invalid_snapshot_payload' }, 400);
        return;
      }

      const blob = await put(pathname, JSON.stringify(snapshot), {
        access: 'private',
        allowOverwrite: true,
        contentType: 'application/json',
        cacheControlMaxAge: 60,
      });
      sendJson(response, { status: 'ok', snapshot: blob.pathname });
      return;
    }

    sendJson(response, { error: 'method_not_allowed' }, 405);
  } catch (error) {
    console.error('[blob] operation failed', error);
    sendJson(response, { error: 'blob_unavailable' }, 500);
  }
}
