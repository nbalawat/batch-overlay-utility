# One cloud machine running the BatchIQ demo (docker compose): the cloud-neutral bootstrap plus the AWS machine module.
# Run it through infra/bin/cloud.py (up, stop, start, down), not by hand.
provider "aws" {
  region = var.region
  dynamic "assume_role" {
    for_each = var.operator_role_arn == null ? [] : [var.operator_role_arn]
    content {
      role_arn     = assume_role.value
      session_name = "batchiq-cloud-machine"
    }
  }
  default_tags {
    tags = merge(var.tags, { "batchiq/managed-by" = "opentofu", "batchiq/stack" = "machine" })
  }
}

module "bootstrap" {
  source          = "../../../modules/common/machine-bootstrap"
  ssh_public_key  = var.ssh_public_key
  git_url         = var.git_url
  git_ref         = var.git_ref
  auto_stop_hours = var.auto_stop_hours
}

module "machine" {
  source                = "../../../modules/aws/machine"
  name                  = var.name
  size                  = var.size
  disk_gb               = var.disk_gb
  user_data             = module.bootstrap.user_data
  allowed_cidrs         = var.allowed_cidrs
  web_ports             = var.web_ports
  running               = var.running
  budget_email          = var.budget_email
  budget_usd            = var.budget_usd
  instance_profile_name = var.instance_profile_name
  tags                  = var.tags
}
