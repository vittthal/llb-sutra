/**
 * API client.
 *
 * Same-origin in production (FastAPI serves the built assets); Vite proxies to
 * localhost:8000 in dev, so no base URL is needed in either case.
 *
 * The free tier sleeps after 15 minutes, so the first request of a session can take
 * up to a minute to wake the instance. Callers get an `onSlow` signal rather than a
 * spinner that looks broken.
 */

const SLOW_AFTER_MS = 2500;

export async function get(path, { onSlow } = {}) {
  const timer = onSlow ? setTimeout(onSlow, SLOW_AFTER_MS) : null;
  try {
    const res = await fetch(path);
    if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
    return await res.json();
  } finally {
    if (timer) clearTimeout(timer);
  }
}

export const getStats = (o) => get('/stats', o);
export const getSubjects = (o) => get('/subjects', o);
export const getSyllabus = (o) => get('/syllabus', o);
export const getActs = (o) => get('/acts', o);
export const getTopics = (subject, o) =>
  get(`/pyq/topics${subject ? `?subject=${encodeURIComponent(subject)}` : ''}`, o);
export const getPyq = (subject, limit = 400, o) =>
  get(`/pyq?subject=${encodeURIComponent(subject || '')}&limit=${limit}`, o);
export const search = (q, subject, limit = 12, o) =>
  get(`/search?q=${encodeURIComponent(q)}&subject=${encodeURIComponent(subject || '')}&limit=${limit}`, o);
