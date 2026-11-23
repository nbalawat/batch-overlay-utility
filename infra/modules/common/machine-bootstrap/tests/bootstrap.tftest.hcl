# Renders the cloud-init document: no cloud, no provider. Proves the settings, the user and the services land where
# the machine expects them, and that bad input is refused before anything is created.
variables {
  ssh_public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMockKeyForTestsOnly batchiq-test"
}

run "renders_defaults" {
  command = plan
  assert {
    condition     = startswith(output.user_data, "#cloud-config\n")
    error_message = "user data must be a cloud-config document"
  }
  assert {
    condition     = strcontains(output.user_data, "GIT_REF=main") && strcontains(output.user_data, "AUTO_STOP_HOURS=10")
    error_message = "the machine settings are missing"
  }
  assert {
    condition     = strcontains(output.user_data, "- ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMockKeyForTestsOnly batchiq-test")
    error_message = "the SSH key is not authorised"
  }
  assert {
    condition     = strcontains(output.user_data, "ssh_pwauth: false") && strcontains(output.user_data, "PasswordAuthentication no") && strcontains(output.user_data, "AllowUsers batchiq")
    error_message = "SSH must allow the one key-only user"
  }
  assert {
    condition     = strcontains(output.user_data, "GIT_URL=https://github.com/nbalawat/batch-overlay-utility.git")
    error_message = "the machine must clone this repository"
  }
  assert {
    condition     = strcontains(output.user_data, "filename: /swapfile")
    error_message = "the small machine needs swap for the first image build"
  }
  assert {
    condition     = strcontains(base64decode(regex("path: /etc/systemd/system/batchiq.service\\n\\s+permissions: \"0644\"\\n\\s+encoding: b64\\n\\s+content: ([A-Za-z0-9+/=]+)", output.user_data)[0]), "User=batchiq")
    error_message = "the stack must run as the machine's user"
  }
  assert {
    condition     = output.forwarded_ports.console == 8080 && output.forwarded_ports.api == 8000
    error_message = "the console and the API must be forwarded on the ports the laptop stack uses"
  }
}

run "custom_settings" {
  command = plan
  variables {
    git_ref         = "claude/some-branch"
    auto_stop_hours = 0
    ssh_user        = "naveen"
  }
  assert {
    condition     = strcontains(output.user_data, "GIT_REF=claude/some-branch") && strcontains(output.user_data, "AUTO_STOP_HOURS=0") && strcontains(output.user_data, "OWNER=naveen")
    error_message = "settings must follow the variables"
  }
  assert {
    condition     = strcontains(output.user_data, "- name: naveen") && strcontains(output.user_data, "AllowUsers naveen")
    error_message = "the user must follow ssh_user"
  }
}

run "refuses_bad_key" {
  command = plan
  variables {
    ssh_public_key = "-----BEGIN OPENSSH PRIVATE KEY-----"
  }
  expect_failures = [var.ssh_public_key]
}

run "refuses_git_over_plain_http" {
  command = plan
  variables {
    git_url = "http://example.com/repo.git"
  }
  expect_failures = [var.git_url]
}
