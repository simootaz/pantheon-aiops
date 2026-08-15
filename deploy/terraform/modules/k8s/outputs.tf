# Outputs from the k8s module.
#
# Phase: 7 - Production Hardening
# 

output "cluster_name" {
  description = "Cluster name."
  value       = var.cluster_name
}

output "kubernetes_version" {
  description = "Control plane version."
  value       = var.kubernetes_version
}
