// Package mcpserver provides the MCP server scaffolding shared by every Go
// connector in Pantheon: transport, request dispatch and error mapping.
//
// Phase: 6 - Go Port & Platform Binaries.
package mcpserver

import "errors"

// ErrNotImplemented is returned by every stub in this package until Phase 6
// replaces it with a working transport.
var ErrNotImplemented = errors.New("mcpserver: not implemented")

// Server dispatches MCP tool calls to the handlers registered against it.
type Server struct {
	name  string
	tools map[string]Tool
}

// New returns a Server that identifies itself to MCP clients as name.
func New(name string) *Server {
	return &Server{
		name:  name,
		tools: make(map[string]Tool),
	}
}

// Name reports the server name advertised to MCP clients.
func (s *Server) Name() string {
	return s.name
}

// Register adds a tool to the server's dispatch table.
//
// TODO: Phase 6 - validate the tool's JSON Schema and reject duplicate names.
func (s *Server) Register(t Tool) error {
	s.tools[t.Name] = t

	return nil
}

// Tools reports the tools registered so far, keyed by tool name.
func (s *Server) Tools() map[string]Tool {
	return s.tools
}

// Serve runs the MCP transport loop until the process is signaled to stop.
//
// TODO: Phase 6 - implement the stdio and streamable HTTP transports.
func (s *Server) Serve() error {
	return ErrNotImplemented
}
