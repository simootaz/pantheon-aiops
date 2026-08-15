# Outputs from the dev environment.
#
# Phase: 7 - Production Hardening
# 

output "object_storage_endpoint" {
  description = "Endpoint the application will use for S3 operations."
  value       = module.object_storage.endpoint
}

output "object_storage_buckets" {
  description = "Buckets Pantheon expects to exist."
  value       = module.object_storage.bucket_names
}

output "cluster_name" {
  description = "Kubernetes cluster name."
  value       = module.k8s.cluster_name
}
