import { get, list, put } from '@vercel/blob';

const SNAPSHOT_PREFIX = 'okr/snapshots/';

function json(body, status = 200) {
  return Response.json(body, {
    status,
    headers: {
      'Cache-Control': 'no-store, max-age=0',
    },
  });
}

function isAuthorized(request) {
  const secret = process.env.CRON_SECRET;
  return Boolean(
    secret && request.headers.get('authorization') === `Bearer ${secret}`,
  );
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

export default async function handler(request) {
  if (!isAuthorized(request)) return json({ error: 'unauthorized' }, 401);

  try {
    if (request.method === 'GET') {
      const snapshot = await readLatestSnapshot();
      return snapshot === null
        ? json({ error: 'snapshot_not_found' }, 404)
        : json(snapshot);
    }

    if (request.method === 'POST') {
      const body = await request.json();
      const pathname = body?.pathname;
      const snapshot = body?.snapshot;

      if (
        typeof pathname !== 'string' ||
        !pathname.startsWith(SNAPSHOT_PREFIX) ||
        !snapshot ||
        typeof snapshot !== 'object' ||
        Array.isArray(snapshot)
      ) {
        return json({ error: 'invalid_snapshot_payload' }, 400);
      }

      const blob = await put(pathname, JSON.stringify(snapshot), {
        access: 'private',
        allowOverwrite: true,
        contentType: 'application/json',
        cacheControlMaxAge: 60,
      });
      return json({ status: 'ok', snapshot: blob.pathname });
    }

    return json({ error: 'method_not_allowed' }, 405);
  } catch (error) {
    console.error('[blob] operation failed', error);
    return json({ error: 'blob_unavailable' }, 500);
  }
}
