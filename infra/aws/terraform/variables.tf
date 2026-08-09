variable "aws_region" {
  description = "AWS region for the ingestion edge resources."
  type        = string
  default     = "us-west-2"
}

variable "project_name" {
  description = "Short project label used in resource names."
  type        = string
  default     = "agentflow"
}

variable "environment" {
  description = "Deployment environment label."
  type        = string
  default     = "dev"
}

variable "ingest_prefix" {
  description = "S3 key prefix for direct cloud ingress objects."
  type        = string
  default     = "incoming/"

  validation {
    condition = (
      length(trim(var.ingest_prefix, "/")) > 0
      && endswith(var.ingest_prefix, "/")
      && !startswith(var.ingest_prefix, "/")
      && !strcontains(var.ingest_prefix, "..")
    )
    error_message = "ingest_prefix must be a relative non-empty prefix ending in a slash."
  }
}

variable "allowed_extensions" {
  description = "File extensions accepted by the validation Lambda."
  type        = list(string)
  default     = [".docx", ".md", ".pdf", ".txt"]

  validation {
    condition = (
      length(var.allowed_extensions) > 0
      && alltrue([for extension in var.allowed_extensions : can(regex("^\\.[A-Za-z0-9]+$", extension))])
    )
    error_message = "allowed_extensions must contain dot-prefixed alphanumeric extensions."
  }
}

variable "max_upload_bytes" {
  description = "Largest object accepted by the validation Lambda and worker."
  type        = number
  default     = 26214400

  validation {
    condition     = var.max_upload_bytes >= 1024 && var.max_upload_bytes <= 26214400
    error_message = "max_upload_bytes must be between 1024 and 26214400 bytes."
  }
}

variable "force_destroy_documents" {
  description = "Allow Terraform to remove a non-empty synthetic or development bucket."
  type        = bool
  default     = false
}

variable "tags" {
  description = "Additional tags applied to all supported resources."
  type        = map(string)
  default     = {}
}
