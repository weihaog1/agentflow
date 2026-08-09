# AWS ingestion edge

This Terraform module creates the narrow cloud edge from the architecture: a private versioned S3 bucket, a validation Lambda, an encrypted SQS queue, and a dead letter queue. The Lambda does not download or parse documents. It validates object-created records and sends normalized ingestion jobs to SQS.

The module intentionally does not choose a production compute platform, PostgreSQL service, or Redis service. A production deployment replaces Compose Postgres with a managed PostgreSQL service that supports pgvector, replaces Compose Redis with a managed disposable cache, runs the API and worker images on the selected container platform, and uses this module's S3 and SQS outputs. The same application business logic remains in the worker.

Initialize and review without applying:

```sh
cd infra/aws/terraform
terraform init
terraform validate
terraform plan
```

Copy `terraform.tfvars.example` only when environment-specific values are needed. The `worker_ingestion_policy_json` output is a least-privilege policy document for the chosen worker runtime role. It grants receive, visibility, queue metadata, and delete operations on only the ingestion queue, plus read access to only the bucket's ingress prefix. The worker deletes an SQS message only after registering the object as a durable PostgreSQL ingestion job. Its normal retry and idempotency behavior then owns parsing, chunking, embedding, and indexing.

Direct cloud uploads use the key contract `incoming/{workspace_id}/{filename.ext}`. The default S3 notification watches only `incoming/`. API-managed objects use a separate `managed/` prefix and do not trigger the Lambda. The normalized queue job includes the parsed `workspace_id`, safe filename, and exact nonempty S3 `versionId`. The default and maximum Terraform ingress limit is 25 MiB, matching the worker upload limit.

The Lambda rejects events from another bucket, non-create events, keys outside the ingress contract, empty or oversized objects, missing event identity fields, and extensions outside the configured allowlist. It validates every record before sending any message. S3 retries a rejected invocation, so bucket notification filters and upload validation should prevent unsupported objects from reaching this path.
