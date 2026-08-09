output "documents_bucket" {
  description = "Versioned S3 bucket for raw document uploads."
  value       = aws_s3_bucket.documents.id
}

output "ingestion_queue_url" {
  description = "SQS URL consumed by the long-running AgentFlow worker."
  value       = aws_sqs_queue.ingestion.url
}

output "ingestion_queue_arn" {
  description = "SQS ARN for worker IAM policy wiring."
  value       = aws_sqs_queue.ingestion.arn
}

output "ingestion_dead_letter_queue_url" {
  description = "Queue URL for ingestion records that exhaust worker retries."
  value       = aws_sqs_queue.ingestion_dead_letter.url
}

output "event_validator_function_name" {
  description = "Thin S3 event validation Lambda name."
  value       = aws_lambda_function.event_validator.function_name
}

output "worker_ingestion_policy_json" {
  description = "Least-privilege policy document to attach to the selected worker runtime role."
  value       = data.aws_iam_policy_document.worker_ingestion.json
}
