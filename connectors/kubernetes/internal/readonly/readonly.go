// Package readonly implements the non-mutating cluster operations: get, list,
// describe, logs, events and top.
//
// Phase: 6 - Go Port & Platform Binaries.
package readonly

import (
	"github.com/simootaz/pantheon-aiops/connectors/kubernetes/internal/client"
	"github.com/simootaz/pantheon-aiops/pkg/mcpserver"
)

// Tools returns the read-only tool set backed by c.
//
// TODO: Phase 6 - implement get, list, describe, logs, events and top.
func Tools(c *client.Client) []mcpserver.Tool {
	if c == nil {
		return nil
	}

	return nil
}
