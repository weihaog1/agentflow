# Security policy

## Supported versions

Security fixes target the latest release and the `main` branch.

## Report a vulnerability

Please use a private GitHub security advisory instead of a public issue:

`https://github.com/weihaog1/agentflow/security/advisories/new`

Include the affected version or commit, reproduction steps, impact, and any suggested mitigation. Do not include real private documents, credentials, access tokens, or personal data in the report.

## Security model

AgentFlow treats uploaded files and extracted document text as untrusted. The project validates upload size and type, stores files under generated object keys, isolates document text from system instructions, avoids persisting hidden model reasoning, and invalidates caches by corpus revision.

The local demo is not an authentication boundary. Do not expose it directly to the public internet. Production deployments must add an authenticated edge, private worker networking, encrypted object storage, managed secrets, and least-privilege IAM.
