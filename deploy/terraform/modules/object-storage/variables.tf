# Inputs for the object-storage module.
#
# Phase: 7 - Production Hardening
# 

variable "endpoint" {
  description = "S3-compatible API endpoint. Empty means the in-cluster MinIO."
  type        = string
  default     = ""
}

variable "region" {
  description = "Region string. MinIO accepts any value."
  type        = string
  default     = "us-east-1"
}

variable "use_ssl" {
  description = "Whether the endpoint is served over TLS."
  type        = bool
  default     = true
}

variable "credentials_secret_name" {
  description = "Name of the secret holding access and secret keys. Never the keys."
  type        = string
  default     = ""
}

variable "force_destroy" {
  description = "Allow buckets to be destroyed while non-empty."
  type        = bool
  default     = false
}

variable "buckets" {
  description = "Logical bucket names Pantheon requires."
  type = object({
    reports   = string
    artifacts = string
    backups   = string
  })
  default = {
    reports   = "pantheon-reports"
    artifacts = "pantheon-artifacts"
    backups   = "pantheon-backups"
  }
}
