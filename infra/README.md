# The demo on a cloud VM

One command puts the whole demo (`docker compose`: the API and the console) on a small virtual machine in your own
cloud account, and takes it away again. It follows the cloud-machine design in
[nbalawat/case-management](https://github.com/nbalawat/case-management) (`infra/cloud`). AWS is implemented first. The
rest is cloud-neutral, so Azure and GCP slot in behind the same contract.

```
infra/bin/cloud.py setup      # once per AWS account, as an administrator
infra/bin/cloud.py up         # create the VM and start the demo (about 10 minutes the first time)
ssh batchiq                   # while this is open the demo is on http://localhost:8080
infra/bin/cloud.py stop       # stop paying for compute; the disk is kept
infra/bin/cloud.py start      # start again (re-admits your current address)
infra/bin/cloud.py down       # delete the VM and everything made for it
infra/bin/cloud.py teardown   # down, then delete everything setup made too
```

## What you need on your laptop

| What | Why | How (macOS) |
|---|---|---|
| AWS credentials for an **administrator** of the account, for `setup` only | `setup` creates an IAM role and an instance profile | `aws configure sso` then `aws sso login --profile <name>` and `export AWS_PROFILE=<name>` (or `aws configure` with an access key) |
| OpenTofu 1.11 or later | creates and deletes the cloud resources | `brew install opentofu` |
| Python 3.9 or later and an OpenSSH client | runs `cloud.py` and reaches the VM | already on a Mac |

Credentials stay in your own AWS CLI configuration. Never put access keys in the repository, in a chat or in an
issue. After `setup`, the other commands run as the least-privilege operator role through the `batchiq-operator`
profile that `setup` writes to `~/.aws/config`. That role can manage the VM, its network, disk and budget, and use the
state bucket, but it cannot create IAM roles or policies.

## What it costs

`up` and `start` print an estimate before they change anything, and `infra/bin/cloud.py cost` prints all of them.
On-demand list prices in us-east-1:

| Size | Machine | Running | Stopped |
|---|---|---|---|
| `small` (default) | t3.medium, 2 vCPU, 4 GB | about $0.05 an hour, $0.45 for an 8-hour day | about $2.40 a month for the 30 GB disk |
| `large` | t3.large, 2 vCPU, 8 GB | about $0.09 an hour | the same |
| `xlarge` | t3.xlarge, 4 vCPU, 16 GB (room for a local LLM) | about $0.17 an hour | the same |

* The VM **stops itself 10 hours after every start** (`--auto-stop 0` turns that off, `ssh batchiq batchiq extend 4`
  pushes it back). Its disk is kept, so `start` brings the demo back as it was.
* Burst credits are set to `standard`, so a busy CPU is throttled rather than billed extra.
* `--budget-email you@example.com` adds a monthly AWS budget ($30 by default, `--budget`) that e-mails at 80% spent
  and 100% forecast.
* `setup` makes nothing that bills by the hour. The state key is about $1 a month. `teardown` removes it.

## How you reach it

Only SSH (port 22) is open, and only to your own public address, which `up` and `start` detect. `setup` adds one
`Include` line to `~/.ssh/config`. After that, `ssh batchiq` signs in with a key that never leaves your laptop
(`~/.batchiq/cloud/aws/machines/batchiq/`) and forwards the console to **http://localhost:8080** and the API to
http://localhost:8000.

To show the demo without the tunnel, `infra/bin/cloud.py up --web` also opens port 8080, still only to your address,
and prints `http://<address>:8080`. Add `--allow <cidr>` (repeatable) to admit another network, for example a client
meeting room. Never use `0.0.0.0/0`: the command and the module both refuse it. The address changes on every start.

## Claude for "Ask the estate" (optional)

The demo runs with the offline assistant by default. To use Claude, send your key to the VM. It travels on SSH's
stdin and lands in the VM's `.env` (mode 600). It never goes into OpenTofu state, user data, the repository or a
process list.

```
printf '%s' "$ANTHROPIC_API_KEY" | infra/bin/cloud.py env ANTHROPIC_API_KEY
ssh batchiq batchiq restart
```

## On the VM

`ssh batchiq batchiq <command>`:

| Command | What it does |
|---|---|
| `status` | the service, the containers, whether the console answers, whether Claude is configured, when the VM stops itself |
| `logs [api\|ui]` | follow the containers' logs |
| `update [REF]` | run another branch, tag or commit (`infra/bin/cloud.py update <ref>` does the same) |
| `restart`, `extend [HOURS]`, `reset --yes` | restart, push the automatic stop back, rebuild from scratch |

## How it is built

```
infra/
  bin/cloud.py                       entry point (standard library only)
  cloud/batchiq_cloud/               the command: lifecycle, SSH, OpenTofu wrapper, one class per cloud (clouds/)
  cloud/tests/                       unit tests with fake OpenTofu, SSH and AWS: no account needed
  contract/                          the cloud-neutral machine contract (variables and the `machine` output)
  modules/common/machine-bootstrap/  cloud-init: Docker, the checkout, a systemd service running docker compose,
                                     the automatic stop, and the on-VM `batchiq` command
  modules/aws/machine/               Ubuntu 24.04 on EC2 in its own VPC: IMDSv2 only, encrypted gp3 disk, SSH-only group
  modules/aws/machine-operator/      the least-privilege operator role and the VM's instance profile
  stacks/aws/bootstrap/              what `setup` creates: encrypted state bucket, KMS state key, the operator module
  stacks/aws/machine/                one VM: bootstrap + machine, state encrypted client-side with the state key
```

To add a cloud, write `modules/<cloud>/machine` against `contract/machine-variables.tf` (`python3
infra/contract/check.py --fix` copies it in), add `stacks/<cloud>/{bootstrap,machine}`, and add a `Cloud` subclass in
`cloud/batchiq_cloud/clouds/`. SSH, cloud-init and the lifecycle are shared.

CI (the `Infra` workflow) checks formatting, the contract, `tofu validate` on every module and stack, the modules'
tests against mocked providers, ShellCheck on the on-VM script, and the command's unit tests on Python 3.9 and 3.12.
None of it needs a cloud account.
