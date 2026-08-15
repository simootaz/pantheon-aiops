# Inputs for the prod environment.
#
# Phase: 7 - Production Hardening
# 

variable "name_prefix" {
  description = "Prefix applied to every resource name."
  type        = string
  default     = "pantheon-prod"
}

variable "object_storage_endpoint" {
  description = "S3-compatible endpoint. Any provider; see ADR 0001."
  type        = string
  default     = "https://s3.example.com"
}

variable "object_storage_region" {
  description = "Region string passed to the S3 client."
  type        = string
  default     = "eu-west-1"
}
