# AWS Credentials Setup Guide

## ❌ Error: `NoCredentialsError: Unable to locate credentials`

This means AWS credentials are not configured on your server.

## ✅ Solution: Configure AWS Credentials

You have 3 options:

### Option 1: Environment Variables (Recommended for Testing)

Add these to your server's environment (e.g., in your systemd service file or `.bashrc`):

```bash
export AWS_ACCESS_KEY_ID=your_access_key_here
export AWS_SECRET_ACCESS_KEY=your_secret_key_here
export AWS_DEFAULT_REGION=ap-south-1
```

**For systemd service**, edit your service file (e.g., `/etc/systemd/system/zapp.service`):

```ini
[Service]
Environment="AWS_ACCESS_KEY_ID=your_access_key_here"
Environment="AWS_SECRET_ACCESS_KEY=your_secret_key_here"
Environment="AWS_DEFAULT_REGION=ap-south-1"
```

Then reload:
```bash
sudo systemctl daemon-reload
sudo systemctl restart zapp
```

### Option 2: AWS Credentials File (Recommended for Production)

Create AWS credentials file on your server:

```bash
mkdir -p ~/.aws
nano ~/.aws/credentials
```

Add this content:
```ini
[default]
aws_access_key_id = your_access_key_here
aws_secret_access_key = your_secret_key_here
region = ap-south-1
```

Set proper permissions:
```bash
chmod 600 ~/.aws/credentials
```

### Option 3: IAM Role (If Running on EC2)

If your server is an EC2 instance, you can attach an IAM role instead of using credentials.

## 🔑 How to Get AWS Credentials

1. Go to **AWS Console** → **IAM** → **Users**
2. Click your user (or create a new one)
3. Go to **Security credentials** tab
4. Click **Create access key**
5. Choose **Application running outside AWS**
6. Copy the **Access key ID** and **Secret access key**

**Important:** Save the secret key immediately - you can't see it again!

## ✅ Verify Credentials Work

Test your credentials:

```bash
# Test S3 access
aws s3 ls s3://my-zid-app-data/

# Test Personalize access
aws personalize list-dataset-groups --region ap-south-1
```

## 🔒 Security Best Practices

- **Never commit credentials to git**
- **Use IAM roles on EC2** when possible
- **Rotate credentials regularly**
- **Use least-privilege IAM policies**

## Required IAM Permissions

Your AWS user/role needs these permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::my-zid-app-data",
        "arn:aws:s3:::my-zid-app-data/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "personalize:*"
      ],
      "Resource": "*"
    }
  ]
}
```

