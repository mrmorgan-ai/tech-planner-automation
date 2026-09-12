/**
 * Anything under /api that no handler claims. Without it the request falls
 * through to the static asset server and the SPA fallback answers with 200 and
 * a page of HTML, so a mistyped endpoint reads as success to the client and
 * only fails later, on parsing.
 *
 * A double-bracket catch-all is the lowest-priority route in Pages, so every
 * real handler still wins.
 */
export const onRequest: PagesFunction = ({ request }) => {
  const { pathname } = new URL(request.url)
  return Response.json({ error: `No such endpoint: ${pathname}` }, { status: 404 })
}
