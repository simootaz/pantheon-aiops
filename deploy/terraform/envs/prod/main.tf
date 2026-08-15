# Pantheon prod environment.
#
# Phase: 7 - Production Hardening
# Production environment: pluggable object storage.
# Point object_storage_endpoint at any S3-compatible provider - a MinIO
# cluster you run, AWS S3, Ceph RGW, Wasabi, B2 or R2. The module and the
# application are identical either way.

module "network" {
  source     = "../../modules/network"
  name       = var.name_prefix
  cidr_block = "10.1.0.0/16"
}

module "k8s" {
  source       = "../../modules/k8s"
  cluster_name = var.name_prefix
  node_count   = 3
}

module "postgres" {
  source     = "../../modules/postgres"
  name       = var.name_prefix
  storage_gb = 100
}

module "redis" {
  source = "../../modules/redis"
  name   = var.name_prefix
}

module "object_storage" {
  source   = "../../modules/object-storage"
  endpoint = var.object_storage_endpoint
  region   = var.object_storage_region
  use_ssl  = true
}
