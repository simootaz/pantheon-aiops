package mcpserver

// This file defines the Tool descriptor and handler types every Go connector
// registers against a Server.
//
// Phase: 6 - Go Port & Platform Binaries.

import "context"

// Handler executes a single MCP tool call. args is the raw JSON argument
// object; the returned bytes are the raw JSON result.
type Handler func(ctx context.Context, args []byte) ([]byte, error)

// Tool is one callable exposed over MCP.
type Tool struct {
	// Name is the MCP tool identifier, for example "k8s_list_pods".
	Name string

	// Description is what the calling agent reads to decide whether to use it.
	Description string

	// Schema is the JSON Schema for the tool's argument object. It is generated
	// from core/contracts/ - never hand-written here.
	Schema []byte

	// Handler executes the call.
	Handler Handler

	// Mutating marks a tool that changes cluster state. Mutating tools must pass
	// through core/guardrails before they are dispatched.
	Mutating bool
}

// TODO: Phase 6 - validate args against Schema before invoking Handler.
