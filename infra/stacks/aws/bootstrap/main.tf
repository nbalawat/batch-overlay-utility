# Run once per AWS account by `infra/bin/cloud.py setup`, with local state and an administrator's credentials: the
# encrypted, versioned state bucket, the key that encrypts state client-side (OpenTofu state encryption), and the cloud
# machine's least-privilege operator role and instance profile. None of it bills by the hour (the key is about $1 a month).
terraform {
  required_version = ">= 1.11.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.0" }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = { "batchiq/managed-by" = "opentofu", "batchiq/stack" = "bootstrap" }
  }
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

# One customer-managed key for state, rotated yearly. A teardown schedules its deletion after AWS's shortest window;
# otherwise 30 days to notice a mistake.
resource "aws_kms_key" "state" {
  description             = "OpenTofu state: bucket encryption and client-side state encryption"
  enable_key_rotation     = true
  rotation_period_in_days = 365
  deletion_window_in_days = var.teardown ? 7 : 30
  policy                  = data.aws_iam_policy_document.state_key.json
}

resource "aws_kms_alias" "state" {
  name          = "alias/${var.prefix}-tofu-state"
  target_key_id = aws_kms_key.state.key_id
}

data "aws_iam_policy_document" "state_key" {
  #checkov:skip=CKV_AWS_109:Key policy resource "*" is the key itself
  #checkov:skip=CKV_AWS_111:Key policy resource "*" is the key itself
  #checkov:skip=CKV_AWS_356:Key policy resource "*" is the key itself
  # Administration stays with the account, as AWS recommends; use is granted by IAM policies (the operator role's).
  statement {
    sid       = "AccountAdministers"
    actions   = ["kms:*"]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = ["arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
  }
}

resource "aws_s3_bucket" "state" {
  #checkov:skip=CKV_AWS_18:State access is recorded by CloudTrail data events; enable them on the account
  #checkov:skip=CKV_AWS_144:State is versioned; cross-region replication is optional per account
  #checkov:skip=CKV2_AWS_62:No consumers of state bucket events
  bucket = "${var.prefix}-tofu-state-${data.aws_caller_identity.current.account_id}"
  # Only `infra/bin/cloud.py teardown` turns this on, in an apply just before it destroys the setup.
  force_destroy = var.teardown
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.state.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    id     = "abort-incomplete-uploads"
    status = "Enabled"
    filter {}
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
  rule {
    id     = "keep-old-state-versions-a-year"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = 365
    }
  }
}

data "aws_iam_policy_document" "state_tls" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.state.arn, "${aws_s3_bucket.state.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "state" {
  bucket     = aws_s3_bucket.state.id
  policy     = data.aws_iam_policy_document.state_tls.json
  depends_on = [aws_s3_bucket_public_access_block.state]
}

# ---- the cloud machine (infra/bin/cloud.py): its least-privilege operator role and the machine's instance profile
module "machine_operator" {
  source                   = "../../../modules/aws/machine-operator"
  prefix                   = var.prefix
  regions                  = length(var.machine_regions) > 0 ? var.machine_regions : [var.region]
  state_bucket_arn         = aws_s3_bucket.state.arn
  state_key_arn            = aws_kms_key.state.arn
  trusted_principals       = var.machine_operators
  permissions_boundary_arn = var.permissions_boundary_arn
}
