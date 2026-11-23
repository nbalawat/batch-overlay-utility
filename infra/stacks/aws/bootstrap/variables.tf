variable "region" {
  description = "Region of the state bucket."
  type        = string
}

variable "prefix" {
  description = "Prefix for the bootstrap resources."
  type        = string
  default     = "batchiq"
}

variable "permissions_boundary_arn" {
  description = "Optional permissions boundary for the operator and machine roles."
  type        = string
  default     = null
}

variable "machine_regions" {
  description = "Regions the cloud machine may run in. Empty: the bootstrap's region."
  type        = list(string)
  default     = []
}

variable "machine_operators" {
  description = "IAM ARNs allowed to assume the cloud machine's operator role. Empty: any identity in the account permitted to assume it."
  type        = list(string)
  default     = []
}

variable "teardown" {
  description = "Set only by `infra/bin/cloud.py teardown`, just before destroying: lets the state bucket be deleted with its contents and shortens the key's deletion window to 7 days."
  type        = bool
  default     = false
}
