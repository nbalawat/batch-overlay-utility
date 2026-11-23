# The cloud machine contract: every cloud's modules/<cloud>/machine takes exactly these variables (this file is copied
# into each as contract.tf; `python3 infra/contract/check.py --fix` copies it, CI fails if a copy drifts) and returns
# one `machine` output with the keys in contract/machine-outputs.md. infra/cloud (the `cloud` command) and the
# machine stacks rely on nothing else, so a new cloud slots in by implementing this module.

variable "name" {
  description = "Name of the machine and prefix of everything created for it."
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,30}$", var.name))
    error_message = "name must be 2-31 lower-case letters, digits or hyphens, starting with a letter."
  }
}

variable "size" {
  description = "small (2 vCPU, 4 GB, enough for the demo), large (2 vCPU, 8 GB) or xlarge (4 vCPU, 16 GB, for a local LLM). Each cloud maps these to its own machine types."
  type        = string
  default     = "small"
  validation {
    condition     = contains(["small", "large", "xlarge"], var.size)
    error_message = "size must be small, large or xlarge."
  }
}

variable "disk_gb" {
  description = "Size of the encrypted system disk, which holds the images and every volume. It survives stop and start; down deletes it."
  type        = number
  default     = 30
  validation {
    condition     = var.disk_gb >= 20 && var.disk_gb <= 500
    error_message = "disk_gb must be between 20 and 500."
  }
}

variable "user_data" {
  description = "Cloud-init document from modules/common/machine-bootstrap. It must not hold secrets."
  type        = string
}

variable "allowed_cidrs" {
  description = "Addresses that may reach SSH (port 22) and any web_ports. Normally the operator's own address as a /32."
  type        = list(string)
  validation {
    condition     = length(var.allowed_cidrs) > 0 && alltrue([for c in var.allowed_cidrs : can(cidrhost(c, 0)) && !contains(["0.0.0.0/0", "::/0"], c)])
    error_message = "allowed_cidrs must list at least one CIDR, and never the whole internet."
  }
}

variable "web_ports" {
  description = "Ports besides SSH that allowed_cidrs (and only they) may reach, for example [8080] to open the console without a tunnel. Empty: SSH only."
  type        = list(number)
  default     = []
  validation {
    condition     = alltrue([for p in var.web_ports : p >= 1024 && p <= 65535 && floor(p) == p])
    error_message = "web_ports must be unprivileged ports (1024-65535)."
  }
}

variable "running" {
  description = "false stops the machine and keeps its disk (only storage bills); true starts it again."
  type        = bool
  default     = true
}

variable "budget_email" {
  description = "When set, a monthly cost budget on the account (or subscription, or project) e-mails here at 80% of budget_usd spent and at 100% forecast."
  type        = string
  default     = ""
  validation {
    condition     = var.budget_email == "" || can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.budget_email))
    error_message = "budget_email must be an e-mail address or empty."
  }
}

variable "budget_usd" {
  description = "Monthly budget in US dollars for budget_email's alerts."
  type        = number
  default     = 30
}

variable "tags" {
  description = "Labels or tags on every resource."
  type        = map(string)
  default     = {}
}
