# Inputs for the redis module.
#
# Phase: 7 - Production Hardening
# 

variable "name" {
  description = "Instance name."
  type        = string
  default     = "pantheon"
}

variable "engine_version" {
  description = "Server major version."
  type        = string
  default     = "7"
}

variable "memory_gb" {
  description = "Allocated memory."
  type        = number
  default     = 1
}
