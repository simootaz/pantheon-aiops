# Inputs for the k8s module.
#
# Phase: 7 - Production Hardening
# 

variable "cluster_name" {
  description = "Cluster name."
  type        = string
  default     = "pantheon"
}

variable "kubernetes_version" {
  description = "Control plane version."
  type        = string
  default     = "1.31"
}

variable "node_count" {
  description = "Worker node count."
  type        = number
  default     = 3
}

variable "node_size" {
  description = "Abstract node size; mapped per provider."
  type        = string
  default     = "medium"
}
