# Inputs for the network module.
#
# Phase: 7 - Production Hardening
# 

variable "name" {
  description = "Name prefix for network resources."
  type        = string
  default     = "pantheon"
}

variable "cidr_block" {
  description = "Primary address range."
  type        = string
  default     = "10.0.0.0/16"
}

variable "enable_nat" {
  description = "Whether private subnets get outbound egress."
  type        = bool
  default     = true
}

variable "availability_zones" {
  description = "Zones to spread subnets across."
  type        = list(string)
  default     = []
}
