module github.com/simootaz/pantheon-aiops/connectors/kubernetes

go 1.25

require github.com/simootaz/pantheon-aiops/pkg/mcpserver v0.0.0

// The shared MCP server package is never published. go.work resolves it inside
// the workspace; this replace keeps `go build` working in this module alone.
replace github.com/simootaz/pantheon-aiops/pkg/mcpserver => ../../pkg/mcpserver
