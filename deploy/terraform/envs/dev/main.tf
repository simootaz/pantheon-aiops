# Pantheon dev environment.
#
# Phase: 7 - Production Hardening
# Development environment: in-cluster MinIO, small footprint.
# object_storage_endpoint is empty, which means 'use the MinIO the Helm
# chart deploys' - no cloud account is involved anywhere in this env.

module "network" {
  source     = "../../modules/network"
  name       = var.name_prefix
  cidr_block = "10.0.0.0/16"
}

module "k8s" {
  source       = "../../modules/k8s"
  cluster_name = var.name_prefix
  node_count   = 1
}

module "postgres" {
  source     = "../../modules/postgres"
  name       = var.name_prefix
  storage_gb = 10
}

module "redis" {
  source = "../../modules/redis"
  name   = var.name_prefix
}

module "object_storage" {
  source   = "../../modules/object-storage"
  endpoint = ""
  region   = "us-east-1"
  use_ssl  = false
}
