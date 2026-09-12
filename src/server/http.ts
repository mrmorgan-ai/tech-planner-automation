/**
 * Restricts a route to one method. Without this, Pages lets an unhandled method
 * fall through to the static asset server, and the SPA fallback answers an API
 * call with 200 and a page of HTML — which reads like success to a client.
 */
export function only<Env>(method: string, handler: PagesFunction<Env>): PagesFunction<Env> {
  return async (context) => {
    if (context.request.method !== method) {
      return Response.json(
        { error: `Only ${method} is allowed on this route` },
        { status: 405, headers: { Allow: method } },
      )
    }
    return handler(context)
  }
}
