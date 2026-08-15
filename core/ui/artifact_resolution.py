"""Resolve an ArtifactRef to a short-lived signed URL. Server-side only.

THE ONLY MODULE THAT TURNS A REFERENCE INTO A FETCHABLE URL.

This mirrors core.cerberus.redemption exactly, and for the same reason. There,
plaintext is produced in one place agents cannot import. Here, a fetchable
destination is produced in one place agents cannot import. In both cases the
agent holds a reference and the server holds the capability.

Never client-side: a signed URL minted in the browser would mean the client
could mint one for any key. Never agent-side: an agent that could resolve could
also read the result, which is the exfiltration path the ArtifactRef design
closes.

Resolution rejects a reference unless:

  1. the object exists in Pantheon's own artifact bucket - the bucket is fixed
     here, not supplied by the caller, so no arbitrary destination is
     expressible; and
  2. it belongs to the same investigation as the surface being rendered. A
     cross-investigation reference is refused, so one run cannot exfiltrate
     another run's artifacts by naming their keys.

Signed URLs are short-lived, for the same reason leases are.

See docs/adr/0006-agentic-ui-protocols.md and
docs/adr/0001-object-storage-minio.md.

Phase: 4 - Delivery Flow
"""

# TODO: Phase 4 - implement resolve(ref, investigation_id) -> signed URL, with
# the bucket fixed server-side and cross-investigation references rejected
