// Package tools assembles the full tool set the Kubernetes MCP server exposes.
//
// Phase: 6 - Go Port & Platform Binaries.
package tools

import (
	"errors"
	"fmt"

	mcpserver "github.com/simootaz/pantheon-aiops/connectors/_base/go"
	"github.com/simootaz/pantheon-aiops/connectors/kubernetes/internal/client"
	"github.com/simootaz/pantheon-aiops/connectors/kubernetes/internal/readonly"
	"github.com/simootaz/pantheon-aiops/connectors/kubernetes/internal/write"
)

// ErrNilDependency reports a missing server or client at registration time.
var ErrNilDependency = errors.New("tools: nil server or client")

// Register adds every Kubernetes tool, read-only and mutating, to srv.
func Register(srv *mcpserver.Server, c *client.Client) error {
	if srv == nil || c == nil {
		return ErrNilDependency
	}

	ro := readonly.Tools(c)
	wr := write.Tools(c)

	all := make([]mcpserver.Tool, 0, len(ro)+len(wr))
	all = append(all, ro...)
	all = append(all, wr...)

	for _, t := range all {
		if err := srv.Register(t); err != nil {
			return fmt.Errorf("register tool %q: %w", t.Name, err)
		}
	}

	return nil
}
