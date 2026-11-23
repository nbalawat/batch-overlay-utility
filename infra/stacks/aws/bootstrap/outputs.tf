output "state_bucket" {
  description = "Bucket that holds each machine's state (machine/<name>.tfstate)."
  value       = aws_s3_bucket.state.bucket
}

output "state_key_arn" {
  description = "KMS key that encrypts the machines' state."
  value       = aws_kms_key.state.arn
}

output "machine_operator_role_arn" {
  description = "Role infra/bin/cloud.py assumes to bring the cloud machine up and down."
  value       = module.machine_operator.operator_role_arn
}

output "machine_instance_profile" {
  description = "Instance profile for the cloud machine."
  value       = module.machine_operator.instance_profile_name
}

output "region" {
  description = "Region of the state bucket and key."
  value       = var.region
}
