// Package client wires client-go: kubeconfig or in-cluster authentication and
// the typed and dynamic clients every Kubernetes tool builds on.
//
// Phase: 6 - Go Port & Platform Binaries.
package client

import "errors"

// ErrNotImplemented is returned until Phase 6 wires client-go.
var ErrNotImplemented = errors.New("client: not implemented")

// Client holds the Kubernetes clients shared by the connector's tools.
type Client struct{}

// New builds a Client from the ambient kubeconfig, falling back to in-cluster
// credentials.
//
// TODO: Phase 6 - implement kubeconfig and in-cluster client construction.
func New() (*Client, error) {
	return nil, ErrNotImplemented
}
