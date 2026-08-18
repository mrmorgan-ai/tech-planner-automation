"""Outbound interfaces. Everything the core needs from the outside world.

Two ports that an early sketch of this layout called for are deliberately
absent, because both turned out to be a second way of doing something the
design already does:

**No `ApprovalGateway`.** Approval is not a callback the core waits on — it is
a separate invocation. `propose_plan` ends at `AwaitingApproval` and returns;
the user's verdict arrives later through a driving adapter, as a call to
`approve_and_create`. The CLI asks at a prompt, the HTTP adapter takes a POST,
and neither needs the core to hold a pending future open across a subprocess
boundary. This also matches how the gate is enforced at the runtime: the
propose pass simply is not permitted to create.

**No `EventPublisher`.** Use cases are async generators that yield
`Event`s, so the driving adapter consumes the stream directly — printing it, or
serializing it to SSE. A publisher port would be an inversion with nothing on
the other side of it.
"""
