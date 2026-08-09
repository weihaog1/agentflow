locals {
  name = "${var.project_name}-${var.environment}"
  tags = merge(
    {
      Application = var.project_name
      Environment = var.environment
      ManagedBy   = "terraform"
    },
    var.tags,
  )
}

resource "aws_s3_bucket" "documents" {
  bucket_prefix = "${local.name}-documents-"
  force_destroy = var.force_destroy_documents
}

resource "aws_s3_bucket_public_access_block" "documents" {
  bucket = aws_s3_bucket.documents.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "documents" {
  bucket = aws_s3_bucket.documents.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_ownership_controls" "documents" {
  bucket = aws_s3_bucket.documents.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_sqs_queue" "ingestion_dead_letter" {
  name                      = "${local.name}-ingestion-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "ingestion" {
  name                       = "${local.name}-ingestion"
  visibility_timeout_seconds = 180
  message_retention_seconds  = 345600
  receive_wait_time_seconds  = 20
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.ingestion_dead_letter.arn
    maxReceiveCount     = 5
  })
}

data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "event_validator" {
  name               = "${local.name}-s3-event-validator"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

resource "aws_iam_role_policy_attachment" "lambda_logs" {
  role       = aws_iam_role.event_validator.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "lambda_queue" {
  statement {
    sid       = "SendNormalizedJobs"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.ingestion.arn]
  }
}

resource "aws_iam_role_policy" "lambda_queue" {
  name   = "send-normalized-ingestion-jobs"
  role   = aws_iam_role.event_validator.id
  policy = data.aws_iam_policy_document.lambda_queue.json
}

data "archive_file" "event_validator" {
  type        = "zip"
  source_file = "${path.module}/../lambda/s3_event_handler.py"
  output_path = "${path.module}/.build/s3_event_handler.zip"
}

resource "aws_cloudwatch_log_group" "event_validator" {
  name              = "/aws/lambda/${local.name}-s3-event-validator"
  retention_in_days = 30
}

resource "aws_lambda_function" "event_validator" {
  function_name    = "${local.name}-s3-event-validator"
  description      = "Validates S3 events and forwards normalized jobs to SQS."
  role             = aws_iam_role.event_validator.arn
  runtime          = "python3.13"
  handler          = "s3_event_handler.lambda_handler"
  filename         = data.archive_file.event_validator.output_path
  source_code_hash = data.archive_file.event_validator.output_base64sha256
  timeout          = 15
  memory_size      = 128

  environment {
    variables = {
      ALLOWED_EXTENSIONS = join(",", var.allowed_extensions)
      EXPECTED_BUCKET    = aws_s3_bucket.documents.id
      INGEST_PREFIX      = var.ingest_prefix
      MAX_OBJECT_BYTES   = tostring(var.max_upload_bytes)
      QUEUE_URL          = aws_sqs_queue.ingestion.url
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.event_validator,
    aws_iam_role_policy.lambda_queue,
    aws_iam_role_policy_attachment.lambda_logs,
  ]
}

resource "aws_lambda_permission" "allow_s3" {
  statement_id   = "AllowS3ObjectCreated"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.event_validator.function_name
  principal      = "s3.amazonaws.com"
  source_arn     = aws_s3_bucket.documents.arn
  source_account = data.aws_caller_identity.current.account_id
}

data "aws_caller_identity" "current" {}

resource "aws_s3_bucket_notification" "documents" {
  bucket = aws_s3_bucket.documents.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.event_validator.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = var.ingest_prefix
  }

  depends_on = [
    aws_lambda_permission.allow_s3,
    aws_s3_bucket_versioning.documents,
  ]
}

data "aws_iam_policy_document" "worker_ingestion" {
  statement {
    sid = "ConsumeIngestionJobs"
    actions = [
      "sqs:ChangeMessageVisibility",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
      "sqs:GetQueueUrl",
      "sqs:ReceiveMessage",
    ]
    resources = [aws_sqs_queue.ingestion.arn]
  }

  statement {
    sid = "ReadIncomingDocumentVersions"
    actions = [
      "s3:GetObject",
      "s3:GetObjectVersion",
    ]
    resources = ["${aws_s3_bucket.documents.arn}/${var.ingest_prefix}*"]
  }
}
