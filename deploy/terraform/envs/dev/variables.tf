# Inputs for the dev environment.
#
# Phase: 7 - Production Hardening
# 

variable "name_prefix" {
  description = "Prefix applied to every resource name."
  type        = string
  default     = "pantheon-dev"
}
