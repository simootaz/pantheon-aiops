# Outputs from the network module.
#
# Phase: 7 - Production Hardening
# 

output "name" {
  description = "Network name prefix."
  value       = var.name
}

output "cidr_block" {
  description = "Primary address range."
  value       = var.cidr_block
}
