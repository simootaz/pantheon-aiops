# Outputs from the postgres module.
#
# Phase: 7 - Production Hardening
# 

output "name" {
  description = "Instance name."
  value       = var.name
}

output "database" {
  description = "Database name."
  value       = var.database
}
