# Inputs for the postgres module.
#
# Phase: 7 - Production Hardening
# 

variable "name" {
  description = "Instance name."
  type        = string
  default     = "pantheon"
}

variable "database" {
  description = "Database to create."
  type        = string
  default     = "pantheon"
}

variable "username" {
  description = "Application role."
  type        = string
  default     = "pantheon"
}

variable "engine_version" {
  description = "Server major version."
  type        = string
  default     = "16"
}

variable "storage_gb" {
  description = "Allocated storage."
  type        = number
  default     = 20
}

variable "credentials_secret_name" {
  description = "Secret holding the password. Never the password."
  type        = string
  default     = ""
}
