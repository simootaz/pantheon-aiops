// Package write implements the mutating cluster operations. Every tool here is
// marked Mutating and is gated by core/guardrails before dispatch.
//
// Phase: 6 - Go Port & Platform Binaries.
package write

import (
	mcpserver "github.com/simootaz/pantheon-aiops/connectors/_base/go"
	"github.com/simootaz/pantheon-aiops/connectors/kubernetes/internal/client"
)

// Tools returns the mutating tool set backed by c.
//
// TODO: Phase 6 - implement scale, rollout restart, cordon and annotate, each
// with dry-run support.
func Tools(c *client.Client) []mcpserver.Tool {
	if c == nil {
		return nil
	}

	return nil
}
