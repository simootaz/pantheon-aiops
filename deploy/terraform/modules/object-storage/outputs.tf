# Outputs from the object-storage module.
#
# Phase: 7 - Production Hardening
# 

output "endpoint" {
  description = "Endpoint the application should use."
  value       = var.endpoint
}

output "region" {
  description = "Region passed through to the S3 client."
  value       = var.region
}

output "bucket_names" {
  description = "Every bucket this module manages."
  value       = values(var.buckets)
}
