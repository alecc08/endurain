/**
 * Builds the `If-Match` header that makes a write to a versioned resource conditional on the
 * version the caller read. The backend refuses a write without it (428) and a stale one (412), so
 * every mutation of a versioned resource sends it.
 *
 * @param version - The row version the caller's copy was read at.
 * @returns The headers to merge into the request.
 */
export function ifMatchHeaders(version: number): { 'If-Match': string } {
  return { 'If-Match': `"${version}"` }
}
