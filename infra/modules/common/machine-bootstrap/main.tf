# The cloud-neutral half of the cloud machine: a cloud-init document that turns a fresh Ubuntu 24.04 machine on any
# cloud into the same Docker Compose stack a laptop runs with `docker compose up`. Each cloud's `machine` module only has to
# boot Ubuntu with this as user data. Nothing secret goes in here: user data is readable by anyone who can describe
# the instance.
locals {
  settings = {
    GIT_URL         = var.git_url
    GIT_REF         = var.git_ref
    AUTO_STOP_HOURS = tostring(var.auto_stop_hours)
    OWNER           = var.ssh_user
  }

  # What the stack publishes, reached from the laptop as http://localhost:<port> through `ssh batchiq`.
  # Docker publishes these on the machine's interfaces, so each cloud's firewall admits SSH (and only the web_ports
  # the operator asked for, from the operator's own address).
  forwarded_ports = {
    console = 8080
    api     = 8000
  }

  user_data = templatefile("${path.module}/cloud-init.yaml.tftpl", {
    ssh_user       = var.ssh_user
    ssh_public_key = trimspace(var.ssh_public_key)
    settings       = join("\n", [for k in sort(keys(local.settings)) : "${k}=${local.settings[k]}"])
    helper         = base64encode(file("${path.module}/files/batchiq.sh"))
    service        = base64encode(templatefile("${path.module}/files/batchiq.service.tftpl", { ssh_user = var.ssh_user }))
    autostop       = base64encode(file("${path.module}/files/batchiq-autostop.service"))
  })
}
