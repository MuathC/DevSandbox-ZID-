# AWS Setup Guide for Personalize

## ✅ What You've Done
- Created S3 bucket: `my-zid-app-data` in region `ap-south-1`

## ❌ What You Still Need

### 1. Create IAM Role for AWS Personalize

AWS Personalize needs an IAM role to read data from your S3 bucket.

#### Step 1: Create the IAM Role

1. Go to **IAM Console** → **Roles** → **Create role**
2. Select **AWS service** → **Personalize**
3. Click **Next**
4. **Attach policies**: You need to attach a policy that allows reading from S3:

   **Option A: Use AWS Managed Policy (Easier)**
   - Search for and attach: `AmazonS3ReadOnlyAccess`
   - This gives read access to ALL S3 buckets (fine for development)

   **Option B: Create Custom Policy (More Secure)**
   - Click **Create policy** → **JSON** tab
   - Paste this policy (replace `my-zid-app-data` with your bucket name):
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Action": [
           "s3:GetObject",
           "s3:ListBucket"
         ],
         "Resource": [
           "arn:aws:s3:::my-zid-app-data",
           "arn:aws:s3:::my-zid-app-data/*"
         ]
       }
     ]
   }
   ```
   - Name it: `PersonalizeS3ReadPolicy`
   - Attach it to your role

5. **Role name**: `PersonalizeS3AccessRole` (or any name you prefer)
6. **Description**: "Allows AWS Personalize to read from S3 bucket"
7. Click **Create role**

#### Step 2: Get the Role ARN

After creating the role:
1. Click on the role name
2. Copy the **Role ARN** (looks like: `arn:aws:iam::123456789012:role/PersonalizeS3AccessRole`)

#### Step 3: Set Environment Variable

Set this environment variable on your server:

```bash
export AWS_PERSONALIZE_ROLE_ARN="arn:aws:iam::YOUR_ACCOUNT_ID:role/PersonalizeS3AccessRole"
```

Or add it to your `.env` file or systemd service file.

### 2. Verify AWS Credentials

Make sure your server has AWS credentials configured:

```bash
# Check if credentials are set
aws configure list

# Or set them manually:
export AWS_ACCESS_KEY_ID=your_access_key
export AWS_SECRET_ACCESS_KEY=your_secret_key
export AWS_DEFAULT_REGION=ap-south-1
```

### 3. S3 Bucket Policy (Optional but Recommended)

Add a bucket policy to your S3 bucket to allow AWS Personalize to read:

1. Go to **S3 Console** → Your bucket `my-zid-app-data`
2. **Permissions** tab → **Bucket policy**
3. Add this policy (replace `YOUR_ACCOUNT_ID` and `YOUR_ROLE_NAME`):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowPersonalizeRead",
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::YOUR_ACCOUNT_ID:role/YOUR_ROLE_NAME"
      },
      "Action": [
        "s3:GetObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::my-zid-app-data",
        "arn:aws:s3:::my-zid-app-data/*"
      ]
    }
  ]
}
```

## Summary

**Required:**
1. ✅ S3 bucket (you have this)
2. ❌ IAM Role for Personalize (create this)
3. ❌ Set `AWS_PERSONALIZE_ROLE_ARN` environment variable (do this)
4. ❌ AWS credentials configured on server (verify this)

**Optional but Recommended:**
- S3 bucket policy (adds extra security)

## Quick Test

After setting up, test if the role works:

```bash
# Test S3 access
aws s3 ls s3://my-zid-app-data/

# Test Personalize access (should list dataset groups)
aws personalize list-dataset-groups --region ap-south-1
```

