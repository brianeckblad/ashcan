# Deployment

**Deploy a Python/Flask application to AWS using Ansible.**

---

## What Gets Deployed

| Component | Details |
|-----------|---------|
| Server | EC2 instance (Ubuntu 22.04) with EBS storage |
| Application | Gunicorn + Nginx, managed by Systemd |
| Storage | S3 bucket |
| Security | IAM role, security groups, no credentials on server |
| Secrets | AWS Secrets Manager |
| SSL | Let's Encrypt (optional) |
| Monitoring | CloudWatch (optional) |

Estimated cost: $10–15/month ($2/month on free tier).

---

## Start Here

Complete [Chapter 1: Prerequisites](docs/guides/PREREQUISITES.md), then choose a deploy path:

| Path | Guide | Time |
|------|-------|------|
| Automated (recommended) | [Quick Start](docs/guides/QUICKSTART.md) | 15–20 min |
| CLI step-by-step | [Manual Deployment](docs/guides/MANUAL_DEPLOYMENT.md) | 1–2 hrs |
| AWS Console (point and click) | [Console Deployment](docs/guides/AWS_CONSOLE_DEPLOYMENT.md) | 1–2 hrs |

The [full guide](docs/README.md) covers deployment, operations, hardening, and teardown in 13 chapters.

---

## Setup

```bash
cd deployment
pip install -r requirements.txt
ansible-galaxy collection install -r requirements.yml --upgrade
./scripts/local-dev-setup.sh
source scripts/load-vars.sh
```
