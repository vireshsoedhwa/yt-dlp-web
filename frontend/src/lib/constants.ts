/** Shared frontend constants.
 *
 * CARD_TTL_MS should match the backend's JOB_CARD_TTL_HOURS setting
 * (defined in backend/app/core/config.py). The backend uses it to filter
 * expired jobs from GET /api/jobs; the frontend uses it to auto-dismiss
 * job cards after the TTL elapses.
 */

export const POLL_INTERVAL_MS = 2000;

export const CARD_TTL_MS = 2 * 60 * 60 * 1000; // 2 hours — match JOB_CARD_TTL_HOURS
